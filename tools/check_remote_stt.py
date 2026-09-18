"""Exercise the Linux Whisper worker with local synthetic speech, without network or playback."""
import json
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import deployment
RUNNER = r'''
import json, re, sys, time
from pathlib import Path
import numpy as np
import soxr
root = Path('/opt/echo')
(root/'local/models').symlink_to('/models')
from tools.prepare_tts import prepare
prepare(root)
from backend.whisper import WhisperClient, available
from backend.speech import synthesize
from backend.settings import EchoSettings
from backend.neural_speech import close
assert available(root)
settings = EchoSettings(tts_engine='pocket', tts_voice='george')
worker = WhisperClient(root)
results = []
try:
    for case, phrase, expected in [
        ('time', 'What time is it?', ['what', 'time']),
        ('question', 'Why does the Moon have phases?', ['moon', 'phases']),
        ('negation', 'Do not turn on the bedroom lights.', ['not', 'bedroom', 'lights']),
        ('silence', None, None),
    ]:
        if phrase:
            source = np.frombuffer(synthesize(phrase, settings=settings), dtype='<i2').astype(np.float32)
            pcm = soxr.resample(source, 48000, 16000).clip(-32768,32767).astype('<i2').tobytes()
        else:
            pcm = bytes(16000*2*3)
        assert len(pcm) <= 16000*2*8
        began = time.monotonic()
        text = worker.transcribe(pcm)
        words = set(re.findall(r"[a-z]+", (text or '').lower()))
        passed = text is None if expected is None else all(word in words for word in expected)
        result = {'case': case, 'passed': passed, 'decode_ms': round((time.monotonic()-began)*1000)}
        results.append(result)
        print(json.dumps(result), flush=True)
        assert passed, case + ' failed'
        del pcm, text
finally:
    worker.close(); close()
print(json.dumps({'result':'PASS','cases':results,'microphone_used':False,'audio_played':False,'network':'none'}))
'''

if __name__ == '__main__':
    run = subprocess.run(['docker', '--context', deployment.docker_context(), 'run', '--rm', '-i', '--init',
        '--network', 'none', '--cpus', '2', '--memory', '3g', '--memory-swap', '3g', '--log-driver', 'none',
        '--mount', 'type=volume,src=echo_models,dst=/models,readonly',
        '--tmpfs', '/opt/echo/local:rw,nosuid,nodev,size=16777216,uid=10000,gid=10000,mode=0700',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=67108864,mode=1777',
        '--entrypoint', 'python', 'echo-host:validation-0.1', '-u', '-'],
        input=RUNNER, text=True, capture_output=True, timeout=150)
    print(run.stdout, end='')
    if run.returncode:
        print(run.stderr[-2500:])
        raise SystemExit(run.returncode)
    receipt = json.loads(run.stdout.splitlines()[-1])
    (ROOT/'local').mkdir(exist_ok=True)
    (ROOT/'local/remote-whisper-check.json').write_text(json.dumps(receipt, indent=2))
