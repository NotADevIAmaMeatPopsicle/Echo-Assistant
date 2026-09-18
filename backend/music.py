"""Opt-in Spotify receiver. Music only enters its pipe; microphone audio never does."""
from hmac import compare_digest
import json
import os
from pathlib import Path
import queue
import secrets
import socket
import subprocess
import threading
import time


class Music:
    def __init__(self, root: Path):
        self.root = root
        self.process = None
        self.socket = None
        self.pcm = queue.Queue(maxsize=64)
        self.stop_event = threading.Event()
        self.status = 'not_configured'
        self.title = self.artist = ''
        self.duration_ms = self.position_ms = 0
        self.position_at = 0.
        self.errors = 0
        self.key = secrets.token_urlsafe(32)
        self.last_pcm = 0.
        self.threads = []
        self.next_restart = 0.
        self.retry_delay = 5.
        self.restart_count = 0
        self.pcm_bytes = self.pcm_frames = self.nonzero_frames = 0
        self.event_count = self.warning_count = 0
        self.last_event = self.last_diagnostic = None
        self.error_categories = {}
        self.discard_pcm = self.pause_pending = False
        self.play_after_transfer = False
        self.pause_after_transfer = False
        self.credential_store = None
        self.next_credential_check = 0.

    def start(self):
        self.status = 'not_configured'
        config_path = self.root/'local/music.json'
        if not config_path.exists(): return
        config = json.loads(config_path.read_text(encoding='utf-8'))
        if config.get('enabled') is not True: return
        from ipaddress import ip_address
        interface = ip_address(config['interface'])
        if interface.version != 4 or not interface.is_private or interface.is_loopback:
            raise ValueError('Spotify requires a private LAN interface')
        if os.environ.get('ECHO_CONTAINER') == '1':
            # The advertised LAN address belongs to Windows; bind mDNS on the
            # container's own interface and let its host helper advertise outward.
            interface = ip_address(socket.gethostbyname(socket.gethostname()))
            if interface.version != 4 or not interface.is_private or interface.is_loopback:
                raise ValueError('Container network is unavailable')
        binary = self.root/'local/runtime/receiver-target/release'/('librespot.exe' if os.name=='nt' else 'librespot')
        if os.environ.get('ECHO_RECEIVER_BINARY'):
            binary = Path(os.environ['ECHO_RECEIVER_BINARY'])
            if not binary.is_absolute(): raise ValueError('Receiver binary must be an absolute path')
        if not binary.exists(): self.status = 'runtime_missing'; return
        self.stop_event.clear()
        self.discard_pcm = self.pause_pending = False
        self.play_after_transfer = False
        self.pause_after_transfer = False
        self.key = secrets.token_urlsafe(32)
        # The subprocess has no voice pipe. Its stdin is a bounded control channel.
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', 0)); self.socket.setblocking(False)
        env = dict(os.environ, ROUND_VOICE_EVENT_KEY=self.key,
            ROUND_VOICE_EVENT_PORT=str(self.socket.getsockname()[1]), RUST_LOG='warn')
        cache = self.root/'local/spotify'
        if os.name != 'nt':
            from .spotify_credentials import SpotifyCredentials
            if cache.resolve() != Path('/run/echo/spotify'):
                raise ValueError('Linux Spotify credentials require the private runtime mount')
            credential_store = SpotifyCredentials(self.root,cache)
            credential_store.restore()
            self.credential_store = credential_store
        cache.mkdir(exist_ok=True)
        temporary = cache/'tmp'; temporary.mkdir(exist_ok=True)
        self.process = subprocess.Popen([str(binary), '--name', 'Round Voice', '--device-type', 'speaker',
            '--backend', 'pipe', '--format', 'S16', '--bitrate', '320', '--disable-audio-cache',
            '--system-cache', str(cache), '--tmp', str(temporary), '--initial-volume', '100',
            '--volume-ctrl', 'linear', '--enable-volume-normalisation', '--autoplay', 'off',
            '--zeroconf-interface', str(interface), '--zeroconf-port', '18899',
            '--onevent', 'round-voice-events'],
            cwd=self.root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.status = 'discoverable'
        self.threads = [threading.Thread(target=self._read_audio, args=(self.process,), name='spotify-pcm', daemon=True),
                        threading.Thread(target=self._drain_errors, args=(self.process,), name='spotify-health', daemon=True)]
        for thread in self.threads: thread.start()

    def _read_audio(self, process):
        import numpy as np
        import soxr
        converter = soxr.ResampleStream(44100, 48000, 1, dtype='int16', quality='HQ')
        carry = b''; output = bytearray()
        try:
            while not self.stop_event.is_set():
                data = process.stdout.read(16384)
                if not data: break
                self.pcm_bytes += len(data)
                carry += data
                end = len(carry)//4*4
                stereo = np.frombuffer(carry[:end], dtype='<i2').reshape(-1, 2)
                mono = (stereo.astype(np.int32).sum(axis=1)//2).astype(np.int16)
                carry = carry[end:]
                output.extend(converter.resample_chunk(mono).tobytes())
                while len(output) >= 512 and not self.stop_event.is_set():
                    if self.discard_pcm or self.status in {'paused', 'stopped'}:
                        # Pipe backends use the consumer as their playback clock.
                        # Draining at CPU speed would race through the track while
                        # the native pause command is still being processed.
                        self.stop_event.wait(min(.1, len(output)/96000))
                        output.clear(); break
                    block = bytes(output[:512])
                    try: self.pcm.put(block, timeout=.2)
                    except queue.Full: continue
                    self.pcm_frames += 1
                    if any(block): self.nonzero_frames += 1
                    del output[:512]; self.last_pcm = time.monotonic()
        except (OSError, ValueError):
            self.errors += 1; self.last_diagnostic = 'pcm_conversion_failed'

    def _drain_errors(self, process):
        # No diagnostic line, account identity, or listening history is persisted.
        while not self.stop_event.is_set():
            line = process.stderr.readline()
            if not line: return
            if b'ERROR' in line: self.errors += 1
            if b'WARN' in line: self.warning_count += 1
            # Fixed classifications only: never retain raw receiver logs, URLs,
            # credentials, account identities, or track names.
            lower = line.lower()
            if b'ERROR' in line:
                categories = (
                    (b'couldn\'t handle connect state command', 'connect_command'),
                    (b'could not dispatch connect state update', 'connect_update'),
                    (b'could not dispatch player event', 'player_event'),
                    (b'player::pause called from invalid state', 'pause_invalid_state'),
                    (b'error handling command', 'player_command'),
                    (b'failed to handle request', 'connect_request'),
                    (b'failed to handle playlist', 'playlist'),
                    (b'player thread error', 'player_thread'),
                    (b'error updating connect state', 'connect_volume'),
                    (b'update after context resolving failed', 'context_update'),
                    (b'on event program', 'event_hook'),
                )
                code = next((code for pattern,code in categories if pattern in lower), 'other')
                self.error_categories[code] = self.error_categories.get(code,0)+1
            if b'on event program' in lower or b'round voice event delivery failed' in lower: self.last_diagnostic = 'event_hook_failed'
            elif b'could not initialize spirc' in lower: self.last_diagnostic = 'spotify_session_failed'
            elif b'authentication' in lower: self.last_diagnostic = 'spotify_authentication_failed'
            elif b'audio key' in lower: self.last_diagnostic = 'spotify_audio_key_failed'
            elif b'failed to load' in lower: self.last_diagnostic = 'spotify_track_load_failed'
            elif b'error' in lower: self.last_diagnostic = 'receiver_error'
            elif b'warn' in lower: self.last_diagnostic = 'receiver_warning'

    def health(self):
        return {'status': self.status, 'errors': self.errors, 'restarts': self.restart_count,
                'sample_rate': 48000, 'pcm_bytes': self.pcm_bytes, 'pcm_frames': self.pcm_frames,
                'nonzero_frames': self.nonzero_frames, 'queue_frames': self.pcm.qsize(),
                'events': self.event_count, 'last_event': self.last_event,
                'warnings': self.warning_count, 'last_diagnostic': self.last_diagnostic,
                'error_categories':dict(self.error_categories), 'pause_pending':self.pause_pending,
                'pause_after_transfer':self.pause_after_transfer}

    def read(self):
        try: return self.pcm.get_nowait()
        except queue.Empty: return None

    def clear(self):
        while self.read() is not None: pass

    def command(self, command):
        if command not in {'play', 'pause', 'toggle', 'next', 'previous', 'transfer'}: raise ValueError('Unsupported music control')
        if not self.process or self.process.poll() is not None: return False
        if command in {'play', 'toggle'} and self.status == 'connected':
            # A newly authenticated receiver is not yet Spotify's active device.
            # Only an explicit Play action takes over the existing session.
            command = 'transfer'; self.play_after_transfer = True
        if command == 'pause' or (command == 'toggle' and self.status == 'playing'):
            # The native player must finish its pipe write before acknowledging
            # pause. Once the speaker stops consuming, a full PCM queue would
            # otherwise deadlock that acknowledgement. Drain/discard immediately;
            # visible playback state still changes only on a receiver event.
            self.discard_pcm = True
            # An idle receiver may ignore Pause without sending a paused event.
            # Do not leave future phone playback waiting for that missing ack.
            self.pause_pending = self.pause_pending or self.status == 'playing'
            self.pause_after_transfer = self.pause_after_transfer or self.play_after_transfer
            self.play_after_transfer = False
            self.clear()
        elif command in {'play', 'transfer'} or command == 'toggle':
            self.discard_pcm = self.pause_pending = self.pause_after_transfer = False
        try: self.process.stdin.write((command+'\n').encode()); return True
        except (BrokenPipeError, OSError): return False

    def poll(self):
        now = time.monotonic()
        if self.credential_store and now >= self.next_credential_check:
            self.next_credential_check = now+2
            self._save_credentials()
        if self.next_restart and now >= self.next_restart:
            self.next_restart = 0.
            self.restart_count += 1
            try: self.start()
            except (OSError, ValueError, RuntimeError):
                self.close(); self.status = 'unavailable'; self.errors += 1
                self.next_restart = now+self.retry_delay
                self.retry_delay = min(60., self.retry_delay*2)
            return
        if self.process and self.process.poll() is not None:
            self.close(); self.status = 'unavailable'; self.errors += 1
            self.next_restart = now+self.retry_delay
            self.retry_delay = min(60., self.retry_delay*2)
            return
        if not self.socket: return
        for _ in range(16):
            try: data, _ = self.socket.recvfrom(4096)
            except BlockingIOError: break
            try:
                event = json.loads(data)
                if not isinstance(event.get('key'), str) or not compare_digest(event['key'], self.key): continue
                kind = event.get('event')
                if kind not in {'receiver_ready', 'track_changed', 'playing', 'paused', 'stopped', 'session_connected', 'session_disconnected', 'volume_changed'}: continue
                self.event_count += 1
                self.last_event = kind
                if kind == 'track_changed':
                    self.title, self.artist = str(event.get('name', ''))[:200], str(event.get('artists', ''))[:200]
                    self.duration_ms = max(0, int(event.get('duration_ms', 0)))
                elif kind in {'playing', 'paused', 'stopped'}:
                    self.status = kind
                    if kind == 'playing':
                        self.retry_delay = 5.
                        self.play_after_transfer = False
                        if self.pause_after_transfer:
                            # Pause sent before activation may have been ignored.
                            # Apply it once the transferred player is actually active.
                            self.pause_after_transfer = False
                            self.command('pause')
                        elif not self.pause_pending: self.discard_pcm = False
                    else:
                        self.pause_pending = False; self.discard_pcm = True
                        self.pause_after_transfer = False
                    self.position_ms = max(0, int(event.get('position_ms', 0))); self.position_at = time.monotonic()
                    if kind != 'playing': self.clear()
                    if kind == 'paused' and self.play_after_transfer:
                        self.play_after_transfer = False; self.command('play')
                elif kind == 'session_connected':
                    # The receiver also emits this when taking active playback,
                    # after our transfer request. Preserve its pending intent;
                    # only disconnect/start establish a new session boundary.
                    self.status = 'connected'
                elif kind == 'session_disconnected':
                    self.play_after_transfer = False
                    self.pause_pending = self.pause_after_transfer = False; self.discard_pcm = True
                    self.status = 'discoverable'; self.clear(); self.title = self.artist = ''
            except (ValueError, TypeError, AttributeError): self.errors += 1

    def close(self):
        self.stop_event.set()
        self.next_restart = 0.
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(b'shutdown\n'); self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                try: self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait(timeout=3)
        for thread in self.threads: thread.join(timeout=1)
        self._save_credentials()
        if self.process:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream: stream.close()
        if self.socket: self.socket.close()
        self.process = self.socket = None
        self.threads = []
        self.clear(); self.status = 'disconnected'; self.title = self.artist = ''

    def _save_credentials(self):
        if self.credential_store:
            try: self.credential_store.persist()
            except (OSError,ValueError,RuntimeError):
                self.errors += 1; self.last_diagnostic = 'credential_storage_failed'
