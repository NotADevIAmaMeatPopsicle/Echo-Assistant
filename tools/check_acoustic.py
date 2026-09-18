"""Explicit, bounded laptop-microphone verification. No recordings or transcripts saved."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


class Capture:
    def __init__(self, seconds=12):
        executable = shutil.which('ffmpeg')
        if not executable: raise RuntimeError('Existing FFmpeg installation required')
        result = subprocess.run([executable, '-hide_banner', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'],
            capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        devices = re.findall(r'"([^"\r\n]+)" \(audio\)', result.stderr.decode('utf-8', errors='replace'))
        if len(devices) != 1: raise RuntimeError('Acoustic check requires one unambiguous microphone')
        self.process = subprocess.Popen([executable, '-hide_banner', '-loglevel', 'error', '-f', 'dshow',
            '-i', 'audio='+devices[0], '-t', str(seconds), '-ac', '1', '-ar', '16000', '-f', 's16le', 'pipe:1'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.pcm = b''
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        self.pcm, _ = self.process.communicate()

    def finish(self):
        self.thread.join(timeout=20)
        if self.thread.is_alive():
            self.process.terminate(); self.thread.join(timeout=3)
            raise RuntimeError('Microphone capture did not finish')
        if self.process.returncode or len(self.pcm) < 32000:
            raise RuntimeError('Microphone capture unavailable')
        pcm, self.pcm = self.pcm, b''
        return pcm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port')
    parser.add_argument('--wifi', action='store_true')
    parser.add_argument('--max-volume', type=int, choices=(1,2,3), default=1)
    args = parser.parse_args()
    capture = Capture(24)
    time.sleep(1)
    command = [sys.executable, '-X', 'utf8', str(ROOT/'tools/check_speaker_device.py'), args.port,
               '--short', '--max-volume', str(args.max_volume)]
    if args.wifi: command.append('--wifi')
    result = subprocess.run(command, capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
    pcm = capture.finish()
    if result.returncode:
        raise RuntimeError('Device spoken test failed; acoustic result not accepted')
    from vosk import Model, KaldiRecognizer, SetLogLevel
    import numpy as np
    SetLogLevel(-1)
    recognizer = KaldiRecognizer(Model(str(ROOT/'local/models/vosk-model-small-en-us-0.15')), 16000)
    recognized = []
    for index in range(0, len(pcm), 8000):
        if recognizer.AcceptWaveform(pcm[index:index+8000]):
            recognized.append(json.loads(recognizer.Result()).get('text', ''))
    recognized.append(json.loads(recognizer.FinalResult()).get('text', ''))
    heard = 'this is echo speaking' in ' '.join(recognized)
    level = np.frombuffer(pcm, dtype='<i2').astype(np.float64)
    print(json.dumps({'acoustic_phrase_detected': heard, 'capture_seconds': round(len(pcm)/32000, 1),
        'microphone_rms': round(float(np.sqrt(np.mean(level*level))), 1),
        'recording_saved': False, 'device': json.loads(result.stdout)}))
    if not heard: raise SystemExit('INCONCLUSIVE: laptop microphone did not recognize the test phrase')


if __name__ == '__main__': main()
