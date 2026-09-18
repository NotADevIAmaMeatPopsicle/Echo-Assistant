"""Silent local TTS acceptance: synthetic text only, PCM in RAM, no device connection."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.neural_speech import NeuralSpeech


def run(engines, transcribe=False):
    recognizer = None
    if transcribe:
        from backend.whisper import WhisperClient
        import numpy as np
        recognizer = WhisperClient(ROOT)
    checks = []
    ready = {'engines':{}}
    path = ROOT/'local/tts-runtime-ready.json'
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(old,dict) and isinstance(old.get('engines'),dict): ready = old
        except (OSError,ValueError): pass
    try:
        for engine in engines:
            ready['engines'][engine] = False
            worker = None
            try:
                started = time.monotonic(); worker = NeuralSpeech(engine)
                load_ms = round((time.monotonic()-started)*1000)
                voices = ['bm_george','am_michael'] if engine=='kokoro' else ['george','charles']
                cases = [('Hello. I am Echo. Your timer is set for five minutes.',voices[0]),
                         ('The room is seventy-two degrees. The lights are off.',voices[0]),
                         ('Done.',voices[0]),
                         ('Hello. I am Echo. Your timer is set for five minutes.',voices[1])]
                for sentence,voice in cases:
                    pcm,metrics = worker.synthesize(sentence,voice)
                    if metrics['network_attempts'] or not 0 < metrics['seconds'] <= 90 or metrics['sample_rate']!=48000:
                        raise RuntimeError('Speech metrics failed validation')
                    item = {'engine':engine,'voice':voice,'synthetic_text':sentence,'load_ms':load_ms,**metrics}
                    if recognizer and sentence!='Done.':
                        samples = np.frombuffer(pcm,dtype='<i2').astype(float)
                        taps = np.sinc(np.arange(-30,31)/3)*np.hamming(61); taps /= taps.sum()
                        reduced = np.convolve(samples,taps,mode='same')[::3].clip(-32768,32767).astype('<i2').tobytes()
                        if len(reduced)<=16000*2*8:
                            item['synthetic_transcription'] = recognizer.transcribe(reduced)
                            if item['synthetic_transcription'] is None: raise RuntimeError('Synthetic speech failed the local recognition confidence gate')
                    checks.append(item); print(json.dumps(item),flush=True)
                    del pcm
                ready['engines'][engine] = True
            finally:
                if worker: worker.close()
                ready['checked_at'] = datetime.now(timezone.utc).isoformat()
                temporary = path.with_suffix('.tmp'); temporary.write_text(json.dumps(ready,indent=2),encoding='utf-8'); temporary.replace(path)
    finally:
        if recognizer: recognizer.close()
        receipt = {'checked_at':datetime.now(timezone.utc).isoformat(),'audio_played':False,
                   'microphone_used':False,'audio_saved':False,'checks':checks,'engines':ready['engines']}
        (ROOT/'local/tts-silent-check.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['kokoro','pocket','all'],default='all')
    parser.add_argument('--transcribe',action='store_true',help='Check synthetic speech with already-installed local Whisper')
    args = parser.parse_args()
    run(['kokoro','pocket'] if args.engine=='all' else [args.engine],args.transcribe)
