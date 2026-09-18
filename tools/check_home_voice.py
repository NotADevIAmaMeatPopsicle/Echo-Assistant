"""Run fixed synthetic speech through local STT and mock HA. Never play or record audio.

This checks recognizer-to-command routing, not the microphone or human speech.
All PCM stays in memory; only content-free case outcomes are saved.
"""
import argparse
import json
from pathlib import Path
import sys

import httpx
import numpy as np
import soxr
from vosk import KaldiRecognizer, Model, SetLogLevel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.home import HomeBridge, HomeConfig
from backend.recognition import accepted_command
from backend.speech import synthesize

CASES = (
    ('set_volume', 'Set the soundbar volume to twenty percent.', 'volume_set', {'volume_level': .2}),
    ('volume_down', 'Turn the soundbar volume down.', 'volume_set', {'volume_level': .08}),
    ('mute', 'Mute the soundbar.', 'volume_mute', {'is_volume_muted': True}),
    ('unmute', 'Unmute the soundbar.', 'volume_mute', {'is_volume_muted': False}),
    ('next_track', 'Next track on the soundbar.', 'media_next_track', {}),
    ('previous_track', 'Previous song on the soundbar.', 'media_previous_track', {}),
    ('volume_query', 'What is the soundbar volume?', None, None),
    ('mute_query', 'Is the soundbar muted?', None, None),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=ROOT/'local/models/vosk-model-small-en-us-0.15')
    args = parser.parse_args()
    SetLogLevel(-1)
    model = Model(str(args.model))
    results = []
    writes = []
    def request(req):
        if req.method == 'POST':
            writes.append((req.url.path, json.loads(req.content)))
            return httpx.Response(200, json=[])
        if req.url.path == '/api/states/media_player.test':
            return httpx.Response(200, json={'state': 'playing', 'attributes': {
                'supported_features': 4 | 8 | 16 | 32, 'volume_level': .1, 'is_volume_muted': False}})
        return httpx.Response(404)
    # MockTransport handles every request. No real HA address, credential, or
    # endpoint is read, and no socket is opened by this adapter.
    home = HomeBridge(HomeConfig(True, 'http://127.0.0.1:1', 'synthetic-test-only',
                      {'soundbar': 'media_player.test'}), httpx.MockTransport(request))
    for case, phrase, service, body in CASES:
        source = np.frombuffer(synthesize(phrase), dtype='<i2').astype(np.float32) / 32768
        samples = soxr.resample(source, 48000, 16000, quality='HQ')
        pcm = (np.clip(samples, -1, 32767/32768) * 32768).astype('<i2').tobytes() + b'\0' * 32000
        recognizer = KaldiRecognizer(model, 16000); recognizer.SetWords(True)
        utterances = []
        for offset in range(0, len(pcm), 512):
            if recognizer.AcceptWaveform(pcm[offset:offset+512]):
                result = json.loads(recognizer.Result())
                if result.get('text'): utterances.append(result)
        final = json.loads(recognizer.FinalResult())
        if final.get('text'): utterances.append(final)
        text = accepted_command(utterances[0]) if len(utterances) == 1 else None
        writes.clear()
        outcome = home.answer(text) if text else None
        expected = [('/api/services/media_player/' + service,
                     {'entity_id': 'media_player.test', **body})] if service else []
        passed = bool(outcome and outcome.get('status') == ('accepted' if service else 'complete') and writes == expected)
        result = {'case': case, 'result': 'PASS' if passed else 'FAIL',
                  'recognized_utterances': len(utterances), 'confidence_accepted': bool(text),
                  'intent_recognized': outcome is not None, 'mock_write_count': len(writes)}
        results.append(result); print(json.dumps(result), flush=True)
        # Do not persist generated PCM or recognizer text.
        del pcm, source, samples, utterances, recognizer
    receipt = {'result': 'PASS' if all(r['result'] == 'PASS' for r in results) else 'FAIL',
               'source': 'offline_synthetic_speech', 'model': args.model.name, 'cases': results,
               'hardware_audio_played': False, 'real_home_actions': False,
               'microphone_used': False}
    (ROOT/'local/home-voice-synthetic.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    if receipt['result'] != 'PASS': raise SystemExit(1)


if __name__ == '__main__': main()
