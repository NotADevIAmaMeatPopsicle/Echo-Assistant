import unittest
from backend.transcription import accepted_transcription


class TranscriptionTests(unittest.TestCase):
    def segment(self, text='Do not mute the soundbar.', **changes):
        return dict(text=text, no_speech_prob=.001, avg_logprob=-.2, compression_ratio=1.2, **changes)

    def test_native_scores_accept_clear_speech_and_preserve_negation(self):
        self.assertEqual(accepted_transcription([self.segment()]), 'Do not mute the soundbar.')
        self.assertEqual(accepted_transcription([self.segment('Do not'), self.segment('mute the soundbar.')]), 'Do not mute the soundbar.')

    def test_any_bad_segment_rejects_the_whole_utterance(self):
        for field, value in [('no_speech_prob', .2), ('no_speech_prob', -1),
                             ('avg_logprob', -1.01), ('avg_logprob', .1),
                             ('compression_ratio', 2.5), ('compression_ratio', -1),
                             ('avg_logprob', float('nan')), ('avg_logprob', True),
                             ('text', ''), ('text', None)]:
            with self.subTest(field=field, value=value):
                bad=self.segment(); bad[field]=value
                self.assertIsNone(accepted_transcription([bad, self.segment('mute the soundbar.')]))

    def test_empty_missing_or_excessive_results_are_rejected(self):
        for value in ([], None, {}, [{}], [self.segment()]*9, [self.segment('x'*1201)]):
            self.assertIsNone(accepted_transcription(value))
