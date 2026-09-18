"""Local phrase detector. No microphone/device I/O or network requests in this module."""
import json
import re

PHRASES = ("hey echo", "okay echo")


def match_wake(result, minimum_confidence=.8):
    """Require a complete, exact two-word phrase and confidence for both words."""
    text = re.sub(r"\s+", " ", result.get("text", "").strip().lower())
    words = result.get("result", [])
    if text not in PHRASES or len(words) != 2:
        return None
    if " ".join(w.get("word", "") for w in words) != text:
        return None
    if any(type(w.get("conf")) not in (int, float) or not .8 <= w["conf"] <= 1
           or w["conf"] < minimum_confidence for w in words):
        return None
    return text


class EchoDetector:
    def __init__(self, model):
        from vosk import KaldiRecognizer
        self.recognizer = KaldiRecognizer(model, 16000, json.dumps([*PHRASES, "[unk]"]))
        self.recognizer.SetWords(True)

    def feed(self, pcm):
        if self.recognizer.AcceptWaveform(pcm):
            return match_wake(json.loads(self.recognizer.Result()))
        return None

    def reset(self):
        self.recognizer.Reset()
