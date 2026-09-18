import unittest
from backend.spoken_reply import spoken_reply


class SpokenReplyTests(unittest.TestCase):
    def test_normal_answers_and_empty_provider_output_remain_speakable(self):
        self.assertEqual(spoken_reply('The Moon reflects sunlight.'),'The Moon reflects sunlight.')
        self.assertTrue(spoken_reply('  '))
        self.assertEqual(len(spoken_reply('a'*1200)),1200)

    def test_long_answers_end_at_a_sentence_and_explain_how_to_continue(self):
        first='The Moon reflects sunlight. '*35
        answer=first+'More detailed explanation follows. '*100
        result=spoken_reply(answer)
        self.assertLessEqual(len(result),1200)
        self.assertTrue(result.endswith(' I can continue if you would like.'))
        prefix=result.removesuffix(' I can continue if you would like.')
        self.assertTrue(prefix.endswith('.'))
        self.assertTrue(answer.startswith(prefix))
        self.assertLessEqual(len(spoken_reply('x'*5000)),1200)


if __name__=='__main__':unittest.main()
