import unittest
from unittest.mock import Mock
from backend.music_voice import music_intent, control_music


class MusicVoiceTests(unittest.TestCase):
    def test_explicit_grammar_leaves_home_and_conversation_alone(self):
        for phrase, action in [('pause the music', 'pause'), ('Stop Spotify!', 'pause'),
                              ('resume music', 'play'), ('next song', 'next'),
                              ('previous track', 'previous'), ('what song is this', 'now_playing')]:
            self.assertEqual(music_intent(phrase), action)
        for phrase in ['pause the soundbar', 'stop the timer', 'my music stopped', 'do not stop music',
                       'next track on the soundbar', 'play the previous song on the soundbar',
                       'mute the soundbar', 'turn the soundbar volume down']:
            self.assertIsNone(music_intent(phrase))

    def test_explicit_pause_cancels_talk_auto_resume(self):
        music = Mock(status='paused'); music.command.return_value = True
        result = control_music(music, 'pause', True)
        self.assertEqual(result, ('accepted', 'Music paused.', False))
        music.command.assert_called_once_with('pause')

    def test_play_waits_for_reply_before_starting_output(self):
        music = Mock(status='connected')
        self.assertEqual(control_music(music, 'play', False), ('accepted', 'Starting music.', True))
        music.command.assert_not_called()

    def test_skip_preserves_whether_talk_interrupted_playback(self):
        for resume in (True, False):
            music = Mock(status='paused'); music.command.return_value = True
            result = control_music(music, 'next', resume)
            self.assertEqual(result[2], resume)
            music.command.assert_called_once_with('next')

    def test_unavailable_control_does_not_claim_success_or_resume(self):
        music = Mock(status='unavailable')
        self.assertEqual(control_music(music, 'play', True)[::2], ('unavailable', False))
        music.command.assert_not_called()
        music.status = 'paused'; music.command.return_value = False
        self.assertEqual(control_music(music, 'pause', True)[::2], ('unavailable', False))

    def test_now_playing_uses_current_metadata_and_preserves_playback(self):
        music = Mock(title='Test song', artist='Test artist')
        self.assertEqual(control_music(music, 'now_playing', True), ('complete', 'Test song by Test artist.', True))
        music.command.assert_not_called()


if __name__ == '__main__': unittest.main()
