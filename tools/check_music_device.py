"""Explicit Spotify transfer and speaker test, with optional in-memory acoustic comparison."""
import argparse
import json
from pathlib import Path
import re
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.cable import Decoder
from backend.music import Music
from backend.speaker import Speaker
from backend.echo import EchoCleaner
from device_transport import make_transport

ROOT = Path(__file__).resolve().parents[1]


def acoustic_match(recording, reference):
    import numpy as np
    import soxr
    sound = np.frombuffer(recording, dtype='<i2').astype(np.float64)
    source = soxr.resample(np.frombuffer(reference, dtype='<i2').astype(np.float64), 48000, 16000)[:48000]
    if len(source) < 16000 or len(sound) < len(source): return 0.
    # Remove DC and emphasize changing audio; no waveform leaves this process.
    sound = np.diff(sound); source = np.diff(source)
    size = 1 << (len(sound)+len(source)-2).bit_length()
    cross = np.fft.irfft(np.fft.rfft(sound, size)*np.fft.rfft(source[::-1], size), size)
    cross = cross[len(source)-1:len(sound)]
    energy = np.concatenate(([0.], np.cumsum(sound*sound)))
    window = energy[len(source):]-energy[:-len(source)]
    denominator = np.sqrt(np.maximum(1., window)*max(1., float(source@source)))
    return round(float(np.max(np.abs(cross)/denominator)), 4)


def echo_stats(pairs):
    import numpy as np
    assert len(pairs) >= 300, 'Too few synchronized microphone/reference frames'
    cleaner = EchoCleaner(); output = []
    try:
        for mic, ref in pairs: output.append(cleaner.process_frame(mic, ref))
    finally: cleaner.close()
    raw = np.frombuffer(b''.join(mic for mic, _ in pairs), dtype='<i2').astype(float)
    ref = np.frombuffer(b''.join(ref for _, ref in pairs), dtype='<i2').astype(float)
    clean = np.frombuffer(b''.join(output), dtype='<i2').astype(float)
    # Allow three seconds for adaptation; compare equal-length in-memory audio.
    start = 48000; end = min(len(raw), len(clean))
    rms = lambda x: float(np.sqrt(np.mean(x*x)))
    original, cleaned = rms(raw[start:end]), rms(clean[start:end])
    return {'paired_frames':len(pairs), 'reference_rms':round(rms(ref), 2),
            'microphone_rms':round(original, 2), 'cleaned_rms':round(cleaned, 2),
            'level_reduction_db':round(float(20*np.log10(max(1.,original)/max(1.,cleaned))), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port')
    parser.add_argument('--wifi', action='store_true')
    parser.add_argument('--max-volume', type=int, choices=(1,2,3), default=1,
                        help='Explicit accepted test ceiling; never changes device volume')
    parser.add_argument('--take-playback', action='store_true', required=True,
                        help='Explicitly move the current Spotify session to this speaker')
    parser.add_argument('--acoustic', action='store_true', help='Compare onboard microphone with music briefly, without saving audio')
    parser.add_argument('--echo', action='store_true', help='Also inspect synchronized echo cancellation in memory, firmware 0.7.0+')
    args = parser.parse_args()
    args.acoustic = args.acoustic or args.echo
    port = make_transport(args); decoder = Decoder(); music = Music(ROOT)
    speaker = Speaker(port.write); latest = {}; network = {}; reference = []; microphone = []; pairs = []
    collect_mic = monitor_ready = False
    ping = time.monotonic()
    def pump():
        nonlocal latest, ping, monitor_ready
        if time.monotonic()-ping >= 1: port.write(b'VOICE_PING\n'); ping = time.monotonic()
        packets, lines = decoder.feed(port.read(8192))
        if collect_mic and len(microphone) < 750: microphone.extend(packets)
        if collect_mic and args.echo and len(pairs) < 750:
            pairs.extend((mic, ref) for mic, ref in zip(packets, decoder.references) if ref is not None)
        for line in lines:
            if line.startswith('STATUS '): latest = dict(re.findall(r'(\w+)=([^ ]+)', line))
            if line.startswith('NETWORK '): network.update(dict(re.findall(r'(\w+)=([^ ]+)', line)))
            if line == 'EVENT mic_monitor=1': monitor_ready = True
            if args.echo and line == 'EVENT mic_duplex=1': monitor_ready = True
            speaker.receive(line)
        music.poll(); speaker.pump()
    def wait_for(predicate, seconds):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            pump()
            if predicate(): return True
        return False
    try:
        port.open()
        if hasattr(port, 'set_buffer_size'): port.set_buffer_size(rx_size=65536, tx_size=65536)
        port.write(b'STATUS\n')
        assert wait_for(lambda: bool(latest), 4), 'Device did not identify itself'
        assert latest.get('product') == 'round-voice' and latest.get('protocol') == '1'
        assert 0 < int(latest.get('volume', 99)) <= args.max_volume, 'Test requires an audible level within the accepted ceiling'
        port.write(b'VOICE_ARM\n')
        music.start()
        if not wait_for(lambda: music.status == 'connected', 30):
            print(json.dumps({'receiver':music.health()})); raise RuntimeError('Spotify authentication did not become ready')
        print('Cached Spotify session ready; requesting playback on Round Voice', flush=True)
        music.command('transfer')
        last_play = 0.
        until = time.monotonic()+30
        while time.monotonic() < until and (music.status != 'playing' or music.pcm.empty()):
            pump()
            if music.status == 'paused' and time.monotonic()-last_play > 2:
                music.command('play'); last_play = time.monotonic()
        if music.status != 'playing' or music.pcm.empty():
            print(json.dumps({'receiver':music.health()})); raise RuntimeError('No current Spotify track could be started')
        if args.acoustic:
            port.write(b'MIC_DUPLEX 1\n' if args.echo else b'MIC_MONITOR 1\n')
            assert wait_for(lambda: monitor_ready, 2), 'Acoustic monitoring requires firmware 0.6.5 or newer'
            collect_mic = True
        def source():
            block = music.read()
            if block and len(reference) < 600: reference.append(block)
            return block
        speaker.start_stream(source)
        wait_for(lambda: False, 8)
        first_frames = speaker.consumed; underruns = speaker.underruns
        collect_mic = False
        port.write(b'MIC_MONITOR 0\n')
        print(json.dumps({'stage':'initial_playback', 'frames':first_frames, 'underruns':underruns, 'receiver':music.health()}), flush=True)
        if first_frames <= 900 or underruns:
            speaker.stop(); music.command('pause'); port.write(b'VOICE_OFF\nSTATUS\n')
            wait_for(lambda: False, .3)
            print(json.dumps({'stage':'failure_diagnostics', 'network':network, 'device':latest,
                'crc_errors':decoder.errors, 'gaps':decoder.gaps,
                'echo':echo_stats(pairs) if args.echo else None}), flush=True)
        assert first_frames > 900 and underruns == 0, 'Speaker failed to consume continuous music'
        speaker.stop(); music.command('pause')
        paused = wait_for(lambda: music.status == 'paused', 4)
        echo = echo_stats(pairs) if args.echo else None
        if args.echo: print(json.dumps({'stage':'echo', **echo, 'recording_saved':False}), flush=True)
        music.clear(); music.command('play')
        resumed = wait_for(lambda: music.status == 'playing' and not music.pcm.empty(), 4)
        print(json.dumps({'stage':'controls', 'paused':paused, 'resumed':resumed, 'receiver':music.health()}), flush=True)
        assert paused and resumed, 'Spotify pause/resume did not complete'
        speaker.start_stream(music.read); wait_for(lambda: False, 3)
        assert speaker.consumed > 250 and speaker.underruns == 0
        speaker.stop(); music.command('pause')
        port.write(b'STATUS\n'); wait_for(lambda: False, .5)
        assert decoder.errors == 0 and latest.get('audio_errors') == '0'
        score = acoustic_match(b''.join(microphone), b''.join(reference)) if args.acoustic else None
        # Disarm before offline processing so its CPU work cannot drop live PCM.
        port.write(b'VOICE_OFF\n')
        print(json.dumps({'result':'PASS', 'delivered_frames':first_frames, 'pause_resume':True,
            'underruns':underruns, 'audio_errors':latest.get('audio_errors'), 'volume':latest.get('volume'),
            'receiver':music.health(), 'acoustic_correlation':score, 'microphone_frames':len(microphone),
            'echo':echo, 'recording_saved':False}), flush=True)
    finally:
        if port.is_open:
            try: port.write(b'MIC_MONITOR 0\nAUDIO_STOP\nVOICE_OFF\n')
            finally: port.close()
        music.close()


if __name__ == '__main__': main()
