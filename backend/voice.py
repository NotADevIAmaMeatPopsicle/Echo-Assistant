"""Opt-in USB voice bridge: local Echo detection, warm dong, bounded command recognition.

Run only when the user has requested wake listening. No audio or transcript files
are written. local/voice-status.json contains health counters, never speech content.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import time
import uuid
import httpx
import serial
from serial.tools import list_ports
from .cable import Decoder
from .wake import PHRASES
from .activation import Activation
from .recognition import Recognition
from .echo import EchoCleaner
from .speaker import Speaker
from .speech import synthesize, prepare as prepare_speech
from .speech_jobs import SpeechJobs, SpeechCancelled, check_cancel
from .reply_request import post_text
from .settings import speech_settings
from .tts_catalog import selected_status
from .neural_speech import close as close_neural_speech
from .display import HomeDisplay
from .music import Music
from .music_voice import music_intent, control_music
from .music_commands import take as take_music_command
from .speaker_check import SpeakerCheck, SAMPLE
from .spoken_reply import spoken_reply
from .alarms import Alarms
from .lifecycle import Lifecycle, request_stop
from .transport import load_wifi, WifiTransport

ROOT = Path(__file__).resolve().parents[1]
MAC = __import__('os').environ.get('ECHO_DEVICE_MAC', '').lower()


def recognition_mode(phase, muted, echo_ready):
    if muted: return None
    if phase == 'music': return 'armed_music' if echo_ready else None
    return phase if phase in {'armed', 'listening'} else None


def activate(port, speaker, music, phase, activation=None):
    """Stop output before the dong; callers preserve existing resume intent."""
    interrupted_music = phase == 'music'
    if interrupted_music:
        music.command('pause'); music.clear()
    if speaker.active: speaker.stop()
    port.write(activation.begin() if activation else b'WAKE\n')
    return interrupted_music


def disconnect_reason(error):
    if isinstance(error, serial.SerialException): return 'serial_io'
    known = {'Microphone stream stopped; disarming': 'microphone_timeout',
             'Expected round board is not present; microphone not armed': 'board_absent',
             'Voice-capable firmware did not identify itself': 'firmware_handshake'}
    return known.get(str(error), type(error).__name__)


def write_status(status):
    path = ROOT / "local/voice-status.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({**status, "updated_at": time.time(), "phrases": PHRASES}), encoding="utf-8")
    # Windows briefly denies replacing an open status file. Health readers must
    # not cause the audio transport and Spotify session to disconnect.
    for attempt in range(5):
        try:
            temporary.replace(path)
            return True
        except PermissionError:
            if attempt < 4: time.sleep(.005)
    return False


def waiting_for_board(status, music):
    """Keep the listener observable and its receiver paused without an output."""
    music.poll()
    if music.status == 'playing' and not music.pause_pending:
        music.command('pause')
    music.clear()
    write_status({**status, 'status': 'connecting', 'music': music.health()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", help="Preferred serial port; exact board identity is always verified")
    parser.add_argument("--stop", action="store_true", help="Ask the current bridge to shut down cleanly")
    parser.add_argument("--model", type=Path, default=ROOT / "local/models/vosk-model-small-en-us-0.15")
    parser.add_argument('--usb', action='store_true', help='Use USB for recovery even when Wi-Fi is paired')
    parser.add_argument('--play-music', action='store_true', help='Explicitly play the existing Spotify session on this speaker after connecting')
    args = parser.parse_args()
    if args.stop:
        print("Stop requested" if request_stop(ROOT) else "No running bridge record", flush=True)
        return
    if not args.model.is_dir():
        raise SystemExit("Local speech model missing; microphone not armed")
    from vosk import Model, SetLogLevel
    SetLogLevel(-1)
    with Lifecycle(ROOT) as lifecycle:
        model = Model(str(args.model))
        recovery = {'connection_failures': 0, 'last_disconnect_reason': None}
        music = Music(ROOT)
        try:
            try: music.start()
            except (OSError, ValueError, KeyError, RuntimeError):
                music.close(); music.status = 'configuration_error'; music.errors += 1
            while not lifecycle.stopped():
                try:
                    run_session(args, lifecycle, model, recovery, music)
                except (serial.SerialException, OSError, RuntimeError, ValueError) as error:
                    recovery['connection_failures'] += 1
                    recovery['last_disconnect_reason'] = disconnect_reason(error)
                    write_status({"status": "disconnected", **recovery, 'music': music.health()})
                    print(f"Bridge disconnected ({recovery['last_disconnect_reason']}); retrying the paired board in three seconds", flush=True)
                    lifecycle.wait(3)
        finally:
            music.close()
            close_neural_speech()


def run_session(args, lifecycle, model, recovery, music):
    sample=SpeakerCheck(ROOT)
    sample_id=None
    wifi = None if args.usb else load_wifi(ROOT)
    if not wifi:
        matches = [p for p in list_ports.comports()
                   if (p.vid, p.pid) == (0x303A, 0x1001) and (p.serial_number or "").lower() == MAC]
        if len(matches) != 1:
            raise RuntimeError("Expected round board is not present; microphone not armed")
        device_port = matches[0].device
    decoder = Decoder()
    status = {"status": "connecting", "transport": "wifi" if wifi else "usb", "connection_id": uuid.uuid4().hex, **recovery, "engine": "vosk-local-prototype", "triggers": 0,
              "pcm_frames": 0, "usb_errors": 0, "usb_gaps": 0, "muted": False,
              "commands": 0, "listen_timeouts": 0, "last_command_status": None, "text_to_speech": "not_configured",
              "spoken_replies": 0, "playback_errors": 0, "music_resume_pending": False}
    write_status(status)
    if wifi:
        port = WifiTransport(wifi, lifecycle, on_wait=lambda: waiting_for_board(status, music))
    else:
        port = serial.Serial(port=None, baudrate=115200, timeout=.01, write_timeout=.2)
        port.dtr = False; port.rts = False; port.port = device_port
    token = (ROOT / "local/api-token").read_text(encoding="utf-8").strip()
    config = speech_settings(ROOT)
    status['text_to_speech'] = selected_status(config,ROOT)
    command = None
    if config.stt_engine == 'whisper':
        from vosk import KaldiRecognizer
        from .whisper import WhisperClient, WhisperCommand
        command = WhisperCommand(KaldiRecognizer(model, 16000), WhisperClient(ROOT))
    recognition = Recognition(model, command=command)
    status['engine'] = 'whisper-base.en-local' if config.stt_engine == 'whisper' else 'vosk-local'
    try:
        port.open()
        if not wifi and hasattr(port, 'set_buffer_size'):
            port.set_buffer_size(rx_size=65536, tx_size=65536)
        with httpx.Client(base_url="http://127.0.0.1:8768", timeout=15, trust_env=False,
                               headers={"Authorization": "Bearer " + token}) as client, ThreadPoolExecutor(max_workers=3) as worker, SpeechJobs(worker) as speech_jobs:
            def spoken_result(outcome, reply, *, cancel=None):
                try:
                    check_cancel(cancel)
                    settings = speech_settings(ROOT)
                    status['text_to_speech'] = selected_status(settings,ROOT)
                    status['speech_worker'] = 'generating'
                    pcm = synthesize(spoken_reply(reply),settings=settings,cancel=cancel)
                    status['speech_worker'] = 'ready'
                except SpeechCancelled:
                    status['speech_worker'] = 'idle'
                    raise
                except (RuntimeError, OSError, TimeoutError):
                    status['speech_worker'] = 'unavailable'
                    pcm = None
                check_cancel(cancel)
                return outcome, reply, pcm

            def answer(text, *, cancel=None):
                try:
                    response = post_text(text,token,cancel=cancel)
                    response.raise_for_status()
                    data = response.json()
                    outcome, reply = data.get("status", "unavailable"), str(data.get("text", "Assistant unavailable"))
                except (httpx.HTTPError, ValueError):
                    outcome, reply = "unavailable", "The local assistant is unavailable right now."
                return spoken_result(outcome, reply,cancel=cancel)

            speaker = Speaker(port.write)
            def finish_sample(result,reason=''):
                nonlocal sample_id
                if sample_id:
                    try:sample.update(sample_id,result,frames=speaker.consumed,underruns=speaker.underruns,reason=reason)
                    except (OSError,ValueError):pass  # A stale check reports failure; metadata cannot interrupt audio.
                    sample_id=None
            display = HomeDisplay(client, worker, port.write)
            alarms = Alarms(client, worker, port.write,speech_jobs)
            pending = None
            port.write(b"STATUS\n")
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                _, lines = decoder.feed(port.read(4096))
                if any("product=round-voice" in line and (re.search(r'\bprotocol=1\b', line) or re.search(r'\bversion=0\.(?:4|5)\.0\b', line)) for line in lines):
                    break
            else:
                raise RuntimeError("Voice-capable firmware did not identify itself")
            if lifecycle.stopped(): return
            duplex = any(re.search(r'\bduplex=1\b', line) for line in lines if line.startswith('STATUS '))
            activation = Activation(any(re.search(r'\bcue_ready=1\b', line) for line in lines if line.startswith('STATUS ')))
            if duplex:
                try: recognition.echo = EchoCleaner()
                except (OSError, RuntimeError): pass  # Talk and idle wake remain usable.
            music.clear(); music.poll()
            port.write(b"VOICE_ARM\n")
            if recognition.echo_ready: port.write(b'MIC_DUPLEX 1\n')
            duplex_enabled = recognition.echo_ready
            status["status"] = "armed"
            status['speech_worker'] = 'loading'
            warming = speech_jobs.submit(prepare_speech,config)
            write_status(status)
            print(f"Echo wake bridge armed over {'paired TLS Wi-Fi' if wifi else 'USB'}; audio stays in local memory", flush=True)
            last_ping = last_status = last_device_status = time.monotonic()
            last_pcm = time.monotonic()
            phase, until, listen_deadline = "armed", 0., 0.
            decoding_shown = False
            resume_music = False
            last_music_ui = 0.
            last_sample_check = 0.
            while not lifecycle.stopped():
                now = time.monotonic()
                if warming and warming.done():
                    try: status['speech_worker'] = warming.result()['status']
                    except (RuntimeError,OSError): status['speech_worker'] = 'unavailable'
                    warming = None
                if now-last_ping >= 1:
                    port.write(b"VOICE_PING\n")
                    last_ping = now
                if now-last_device_status >= 5:
                    port.write(b"STATUS\n"); last_device_status = now
                previous_errors, previous_gaps = decoder.errors, decoder.gaps
                packets, lines = decoder.feed(port.read(4096))
                if (decoder.errors, decoder.gaps) != (previous_errors, previous_gaps):
                    recognition.reset()
                for line in lines:
                    if phase == 'activation': activation.receive(line)
                    display.receive(line)
                    cancelled_alarm = alarms.receive(line)
                    if cancelled_alarm and phase == 'alarm':
                        speaker.stop(); phase, until = 'cooldown', now+1; last_pcm = now
                    try: speaker.receive(line)
                    except RuntimeError:
                        status["playback_errors"] += 1
                        finish_sample('failed','Speaker playback failed')
                        if phase == 'alarm': alarms.retry()
                        if phase == 'music': music.command('pause')
                        phase, until = "cooldown", now+1
                        last_pcm = now
                    if line.startswith("STATUS "):
                        device = dict(re.findall(r"(\w+)=([^ ]+)", line))
                        status["device"] = {k: device.get(k) for k in
                            ("wake", "stream", "stream_drops", "usb_drops", "audio_errors", "peak", "volume", "transport", "network", "rssi", "version", "uptime_ms", "heartbeat_ms")}
                        status["muted"] = device.get("muted") == "1"
                    elif line.startswith('NETWORK '):
                        status['network'] = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
                    elif line.startswith('USB '):
                        status['usb_link'] = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
                    elif line.startswith('BUTTON '):
                        status['mute_button'] = {key:int(value) for key,value in re.findall(r'\b(ready|level|toggles|errors|lower_level|upper_presses|lower_presses)=(-?\d+)',line)}
                    elif line.startswith('UI '):
                        status['display'] = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
                    elif line.startswith('RENDER '):
                        fields = dict(re.findall(r'(\w+)=([^ ]+)', line))
                        status['render'] = {'state': fields.get('state'), **{
                            key: int(fields[key]) for key in ('last_us', 'max_us', 'frames', 'compose_us', 'flush_us', 'cache_pixels', 'background')
                            if fields.get(key, '').isdigit()}}
                    elif line.startswith("EVENT mic_muted="):
                        finish_sample('cancelled')
                        status["muted"] = line.endswith("=1")
                        if status['muted']:
                            if phase=='alarm' and alarms.is_announcement:
                                speaker.stop();phase,until='cooldown',now+.4
                            alarms.messages.cancel()
                        if not status['muted'] and recognition.echo_ready:
                            port.write(b'MIC_DUPLEX 1\n')
                        last_pcm = now
                        if phase not in {'music', 'alarm'}: phase = "armed"
                        recognition.reset()
                        if pending: pending.cancel(); pending = None
                        if speaker.active and phase not in {'music', 'alarm'}: speaker.stop()
                    elif line == "EVENT cancelled=1":
                        finish_sample('cancelled')
                        if phase == 'alarm': alarms.finished('cancelled')
                        alarms.messages.cancel()
                        phase, until = "cooldown", now+2
                        recognition.reset()
                        if pending: pending.cancel(); pending = None
                        if speaker.active: speaker.stop()
                        resume_music = False
                    elif line == "EVENT talk=1" and not status["muted"]:
                        finish_sample('cancelled')
                        last_pcm = now
                        if phase == 'alarm': alarms.finished('cancelled')
                        alarms.messages.cancel()
                        if pending: pending.cancel(); pending = None
                        resume_music = activate(port, speaker, music, phase, activation) or resume_music
                        phase = "activation"
                        recognition.reset()
                    elif line.startswith("EVENT music_action="):
                        action = line.partition('=')[2]
                        if action in {'toggle', 'next', 'previous'}:
                            music.command(action)
                display.pump()
                alarms.pump()
                if phase=='alarm' and alarms.is_announcement and alarms.messages.stop_requested:
                    speaker.stop();alarms.finished('cancelled');phase,until='cooldown',now+.4;last_pcm=now
                requested_music=take_music_command(ROOT,lifecycle.identity)
                if requested_music:
                    # An explicit Pause also cancels Talk/alarm's deferred resume.
                    # It must not interrupt the current spoken answer or cue.
                    if requested_music=='pause': resume_music=False
                    music.command(requested_music)
                music.poll()
                if now-last_sample_check>=.1:
                    last_sample_check=now
                    try:
                        if sample_id and (sample.cancelled(sample_id,lifecycle.identity)
                                or not 1<=int(status.get('device',{}).get('volume',99))<=3):
                            if pending:pending.cancel();pending=None
                            if speaker.active:speaker.stop()
                            finish_sample('cancelled')
                            port.write(b'VOICE_DONE\n');phase,until='cooldown',now+.4;last_pcm=now
                        if not sample_id:
                            sample_id=sample.claim(lifecycle.identity,{**status,'status':phase,'music':music.health(),
                                                                    'speaker':{'active':speaker.active}})
                            if sample_id:
                                port.write(b'VOICE_THINKING\nSTATUS\n')
                                pending=speech_jobs.submit(spoken_result,'complete',SAMPLE)
                                phase='thinking';recognition.reset()
                    except (OSError,ValueError):pass
                if args.play_music and music.status in {'connected', 'paused', 'playing'}:
                    args.play_music = False
                    music.command('play')
                if phase == "music" and music.status in {'paused', 'stopped', 'unavailable', 'discoverable'}:
                    speaker.stop(); phase, until = "cooldown", now+.4; last_pcm = now
                if phase == 'music' and music.last_pcm and now-music.last_pcm > 5:
                    speaker.stop(); music.command('pause'); music.clear()
                    status['playback_errors'] += 1
                    phase, until = 'cooldown', now+1; last_pcm = now
                if phase == "armed" and music.status == 'playing' and not music.pcm.empty():
                    speaker.start_stream(music.read); phase = "music"
                if phase in {'armed', 'music'}:
                    alarm_pcm = alarms.take(allow_announcements=not status['muted'])
                    if alarm_pcm:
                        if phase == 'music': music.command('pause'); music.clear(); resume_music = True
                        if alarms.is_announcement:port.write(b'VOICE_REPLY Room announcement\n')
                        speaker.start(alarm_pcm, kind='V' if alarms.is_announcement else 'A'); phase = 'alarm'
                if now-last_music_ui >= 1:
                    safe = lambda text: re.sub(r'[^ -~]', ' ', str(text))[:28]
                    port.write(f"MUSIC_STATE {safe(music.status)}\nMUSIC_TITLE {safe(music.title)}\nMUSIC_ARTIST {safe(music.artist)}\n".encode())
                    status['music'] = music.health()
                    last_music_ui = now
                if pending and pending.done():
                    try: outcome, reply, pcm = pending.result()
                    except Exception:
                        outcome, reply, pcm = "unavailable", "Local reply unavailable", None
                    pending = None
                    status["last_command_status"] = outcome
                    safe_reply = re.sub(r"[^ -~]", "", reply.replace(chr(176), " "))[:28]
                    port.write(("VOICE_REPLY " + safe_reply + "\n").encode("ascii"))
                    if pcm and not status["muted"]:
                        speaker.start(pcm); phase = "speaking"
                        if sample_id:
                            try:sample.update(sample_id,'playing')
                            except (OSError,ValueError):pass
                    else:
                        status["playback_errors"] += 1
                        finish_sample('failed','Local speech generation failed')
                        phase, until = "cooldown", now+1
                if phase in {"speaking", "music", "alarm"}:
                    try: speaker.pump()
                    except RuntimeError:
                        status["playback_errors"] += 1
                        finish_sample('failed','Speaker playback failed')
                        if phase == "music": music.command('pause')
                        if phase == 'alarm': alarms.retry()
                        phase, until = "cooldown", now+1
                        last_pcm = now
                    if phase in {'speaking', 'alarm'} and not speaker.active:
                        if phase == 'alarm': alarms.finished('played' if speaker.consumed>0 and speaker.underruns==0 else 'failed')
                        elif sample_id:
                            complete=speaker.consumed>0 and speaker.underruns==0
                            finish_sample('complete' if complete else 'failed','' if complete else 'Speaker playback was incomplete')
                            status['speaker_checks']=status.get('speaker_checks',0)+int(complete)
                        else: status["spoken_replies"] += 1
                        phase, until = "cooldown", now+1
                        last_pcm = now
                if phase == "activation":
                    next_phase = activation.poll()
                    if next_phase == 'listening':
                        phase = 'listening'; listen_deadline = now+8
                        decoding_shown = False
                    elif next_phase == 'timeout':
                        status['last_command_status'] = 'cue_timeout'
                        port.write(b'VOICE_TIMEOUT\n')
                        phase, until = 'cooldown', now+1
                if phase == 'listening' and recognition.decoding.is_set() and not decoding_shown:
                    port.write(b'VOICE_THINKING\n')
                    listen_deadline = now+14
                    decoding_shown = True
                if phase == "listening" and now >= listen_deadline:
                    status['listen_timeouts'] += 1
                    status['last_command_status'] = 'not_understood'
                    port.write(b"VOICE_TIMEOUT\n")
                    phase, until = "cooldown", now+1
                if phase == "cooldown" and now >= until:
                    phase = "armed"
                    if resume_music:
                        music.command('play'); resume_music = False
                recognition.set_mode(recognition_mode(phase, status['muted'], recognition.echo_ready))
                for event in recognition.poll():
                    if phase in {'armed', 'music'} and event['kind'] == 'wake':
                        alarms.messages.cancel()
                        resume_music = activate(port, speaker, music, phase, activation) or resume_music
                        status['triggers'] += 1
                        phase = 'activation'
                        print('Echo wake detected; activation dong requested', flush=True)
                    elif phase == 'listening' and event['kind'] == 'command':
                        status['commands'] += 1; port.write(b'VOICE_THINKING\n')
                        intent = music_intent(event['value'])
                        if intent:
                            outcome, reply, resume_music = control_music(music, intent, resume_music)
                            pending = speech_jobs.submit(spoken_result, outcome, reply)
                        else:
                            pending = speech_jobs.submit(answer, event['value'])
                        phase = 'thinking'
                recognition.set_mode(recognition_mode(phase, status['muted'], recognition.echo_ready))
                for pcm, reference in zip(packets, decoder.references):
                    status['pcm_frames'] += 1; last_pcm = now
                    recognition.submit(pcm, reference)
                status['recognition'] = recognition.health()
                status['music_wake'] = status['recognition']['echo']
                status['music_resume_pending'] = resume_music
                if duplex_enabled and not recognition.echo_ready:
                    port.write(b'MIC_DUPLEX 0\n'); duplex_enabled = False
                if not status['recognition']['alive']: raise RuntimeError('Recognition worker stopped')
                status.update(usb_errors=decoder.errors, usb_gaps=decoder.gaps)
                status['framing'] = {'header': decoder.header_errors, 'checksum': decoder.checksum_errors,
                                     'noise': decoder.noise_errors, 'console_interference': decoder.console_frames}
                status['speaker'] = {'active': speaker.active, 'kind': speaker.kind, 'frames': speaker.consumed, 'underruns': speaker.underruns}
                if now-last_pcm > 4 and not status["muted"] and phase not in {"speaking", "music", "alarm"}:
                    raise RuntimeError("Microphone stream stopped; disarming")
                status['phase'] = phase
                status['announcement'] = alarms.is_announcement
                status["status"] = "muted" if status["muted"] else phase
                if now-last_status >= 1:
                    write_status(status); last_status = now
    except KeyboardInterrupt:
        pass
    finally:
        if sample_id:
            try:sample.update(sample_id,'failed',reason='Speaker connection ended')
            except (OSError,ValueError):pass
        recognition.close()
        # Preserve the authenticated receiver across board reconnects. Pause the
        # lost output and discard queued samples; Spotify stays selectable.
        music.command('pause'); music.clear()
        if port.is_open:
            try: port.write(b"VOICE_OFF\n")
            except OSError: pass
            port.close()
        status["status"] = "disconnected"
        status['music_resume_pending'] = False
        write_status(status)


if __name__ == "__main__":
    main()
