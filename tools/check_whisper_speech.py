"""Evaluate local Whisper using fixed synthetic speech. No microphone, playback or real HA."""
import json
from pathlib import Path
import sys
import time

import httpx
import numpy as np
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.home import HomeBridge, HomeConfig
from backend.transcription import accepted_transcription
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
    ('negated_mute', 'Do not mute the soundbar.', 'reject', None),
    ('negated_unmute', "Don't unmute the soundbar.", 'reject', None),
    ('narrative', 'The soundbar volume was twenty percent.', 'reject', None),
    ('unrelated', 'The garden looks lovely today.', 'reject', None),
    ('silence', None, 'no_speech', None),
    ('noise', None, 'no_speech', None),
)


def main():
    model = WhisperModel(str(ROOT/'local/models/faster-whisper-base.en'), device='cpu',
                         compute_type='int8', cpu_threads=4, num_workers=1, local_files_only=True)
    writes = []; results = []
    def request(req):
        if req.method == 'POST':
            writes.append((req.url.path, json.loads(req.content)))
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={'state': 'playing', 'attributes': {
            'supported_features': 4 | 8 | 16 | 32, 'volume_level': .1, 'is_volume_muted': False}})
    home = HomeBridge(HomeConfig(True, 'http://127.0.0.1:1', 'synthetic-test-only',
                      {'soundbar': 'media_player.test'}), httpx.MockTransport(request))
    # FIR before 48 -> 16 kHz decimation. This affects only generated fixtures;
    # the physical device already sends filtered 16 kHz microphone frames.
    taps = np.arange(63) - 31
    kernel = np.sinc(2 * (7000/48000) * taps) * np.hamming(63)
    kernel /= kernel.sum()
    for case, phrase, service, body in CASES:
        if phrase is None:
            source = np.zeros(48000 * 3, dtype=np.float32) if case == 'silence' else np.random.default_rng(12).normal(0, .003, 48000 * 3).astype(np.float32)
        else:
            source = np.frombuffer(synthesize(phrase), dtype='<i2').astype(np.float32) / 32768
        pcm = np.convolve(source, kernel, mode='same')[::3].astype(np.float32)
        began = time.monotonic()
        segments, _ = model.transcribe(pcm, language='en', beam_size=5, word_timestamps=True,
                                       condition_on_previous_text=False, vad_filter=False)
        segments = list(segments)
        decoded = {'text': ''.join(s.text for s in segments).strip(),
                   'result': [{'word': w.word, 'conf': w.probability} for s in segments for w in s.words or []]}
        text = accepted_transcription([{'text': s.text, 'no_speech_prob': s.no_speech_prob,
                                       'avg_logprob': s.avg_logprob, 'compression_ratio': s.compression_ratio}
                                      for s in segments])
        writes.clear(); outcome = home.answer(text) if text else None
        expected = [('/api/services/media_player/' + service, {'entity_id': 'media_player.test', **body})] if service not in {None, 'reject', 'no_speech'} else []
        passed = (text is None and not writes) if service == 'no_speech' else (outcome is None and not writes) if service == 'reject' else bool(
            outcome and outcome['status'] == ('accepted' if service else 'complete') and writes == expected)
        result = {'case': case, 'result': 'PASS' if passed else 'FAIL', 'confidence_accepted': bool(text),
                  'mock_write_count': len(writes), 'decode_ms': round((time.monotonic()-began)*1000),
                  'max_no_speech_probability': round(max((s.no_speech_prob for s in segments), default=1), 4),
                  'min_avg_logprob': round(min((s.avg_logprob for s in segments), default=-99), 4)}
        results.append(result); print(json.dumps(result), flush=True)
        if not passed:
            # These are fixed generated test phrases, never captured speech.
            print(json.dumps({'synthetic_text': decoded['text'], 'low_words': [w for w in decoded['result'] if w['conf'] < .8]}), flush=True)
        del pcm, source, segments, decoded
    receipt = {'result': 'PASS' if all(r['result'] == 'PASS' for r in results) else 'FAIL',
               'model': 'faster-whisper-base.en', 'cases': results,
               'microphone_used': False, 'hardware_audio_played': False, 'real_home_actions': False}
    (ROOT/'local/whisper-synthetic.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    if receipt['result'] != 'PASS': raise SystemExit(1)


if __name__ == '__main__': main()
