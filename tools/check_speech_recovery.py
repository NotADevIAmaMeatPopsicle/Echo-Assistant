"""Exercise real local speech cancellation/reload without microphone or playback."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from threading import Event
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import neural_speech
from backend.settings import EchoSettings
from backend.speech import synthesize_checked
from backend.speech_jobs import SpeechCancelled


def main():
    checks=[]
    try:
        for engine in ('pocket','kokoro'):
            settings=EchoSettings(tts_engine=engine)
            started=time.monotonic(); neural_speech.prepare(settings)
            load_ms=round((time.monotonic()-started)*1000)
            pcm,first=synthesize_checked('Hello. I am Echo.',settings=settings)
            assert first['load_ms']==0 and pcm
            del pcm
            old=neural_speech._worker
            original_get=old._get
            waiting=Event(); cancel=Event()
            def wait(*args):
                waiting.set()
                return original_get(*args)
            old._get=wait
            with ThreadPoolExecutor(1) as executor:
                pending=executor.submit(synthesize_checked,'This is a synthetic cancellation check. '*25,
                                        settings=settings,cancel=cancel)
                assert waiting.wait(3),'Generation did not begin'
                stopped=time.monotonic(); cancel.set()
                try: pending.result(timeout=3)
                except SpeechCancelled: pass
                else: raise AssertionError('Cancelled audio was delivered')
                cancellation_ms=round((time.monotonic()-stopped)*1000)
                assert old.process.poll() is not None,'Cancelled process remained alive'
            pcm,recovered=synthesize_checked('Your timer is ready.',settings=settings)
            assert pcm and neural_speech._worker is not old and recovered['load_ms']>0
            del pcm
            checks.append({'engine':engine,'load_ms':load_ms,'warm_generation_ms':first['generation_ms'],
                           'cancellation_ms':cancellation_ms,'old_process_exited':True,
                           'reload_ms':recovered['load_ms'],'recovered':True,
                           'network_attempts':recovered['network_attempts']})
            print(json.dumps(checks[-1]),flush=True)
            neural_speech.close()
        pcm,sapi=synthesize_checked('Hello. I am Echo.',settings=EchoSettings())
        assert pcm and sapi['sample_rate']==48000
        del pcm
        checks.append({'engine':'sapi','generation_ms':sapi['generation_ms'],'nonempty_pcm':True})
        receipt={'checked_at':datetime.now(timezone.utc).isoformat(),'audio_played':False,
                 'microphone_used':False,'audio_saved':False,'checks':checks}
        (ROOT/'local/speech-recovery-check.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    finally: neural_speech.close()


if __name__=='__main__': main()
