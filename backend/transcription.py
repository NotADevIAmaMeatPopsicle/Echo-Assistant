"""Quality gate for offline Whisper command utterances; no device or network I/O."""
import math


def accepted_transcription(segments):
    # Whisper log probabilities are not Vosk word confidences. Use its native
    # speech/log-probability/repetition measures: default logprob=-1.0 and
    # repetition=2.4, with no_speech=0.2 rather than the default 0.6. Reject the whole utterance if any
    # segment is uncertain; dropping a segment could remove a negation.
    if not isinstance(segments, list) or not 1 <= len(segments) <= 8:
        return None
    text = []
    for segment in segments:
        if not isinstance(segment, dict): return None
        words = segment.get('text')
        if not isinstance(words, str) or not words.strip(): return None
        speech = segment.get('no_speech_prob')
        probability = segment.get('avg_logprob')
        repetition = segment.get('compression_ratio')
        if not all(type(value) in {int, float} and math.isfinite(value)
                   for value in (speech, probability, repetition)):
            return None
        if not (0 <= speech < .2 and -1 <= probability <= 0 and 0 <= repetition <= 2.4):
            return None
        text.append(words.strip())
    result = ' '.join(text)
    return result if len(result) <= 1200 else None
