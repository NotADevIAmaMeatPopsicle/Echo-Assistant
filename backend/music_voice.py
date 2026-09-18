"""Explicit voice music controls, evaluated on the bridge thread without recording text."""
import re


def music_intent(text):
    query = re.sub(r'\s+', ' ', text.lower().strip().rstrip('.?!'))
    for action, verbs in (('play', 'play|resume'), ('pause', 'pause|stop')):
        if re.fullmatch(rf'(?:{verbs}) (?:the )?(?:music|spotify)', query): return action
    if query in {'next song', 'next track', 'skip this song', 'skip this track', 'skip song'}: return 'next'
    if query in {'previous song', 'previous track', 'go back a song', 'go back a track'}: return 'previous'
    if query in {"what's playing", 'what is playing', 'what song is this', 'what is this song'}: return 'now_playing'
    return None


def control_music(music, intent, resume_after_reply):
    """Return outcome, spoken reply, and whether to resume after the reply ends."""
    if intent == 'now_playing':
        if not music.title:
            return 'complete', 'No song is selected on this speaker.', resume_after_reply
        title, artist = music.title[:150], music.artist[:150]
        return 'complete', title + (' by '+artist if artist else '') + '.', resume_after_reply
    if music.status not in {'connected', 'playing', 'paused', 'stopped'}:
        return 'unavailable', 'Spotify is unavailable right now.', False
    if intent == 'play':
        # Delay playback until the spoken acknowledgement has drained. Play can
        # explicitly transfer a cached Spotify session when this device is idle.
        return 'accepted', 'Starting music.', True
    if intent not in {'pause', 'next', 'previous'}: raise ValueError('Unsupported music intent')
    if intent != 'pause' and music.status == 'connected':
        return 'unavailable', 'Choose music in Spotify first.', False
    if not music.command(intent):
        return 'unavailable', 'Spotify did not accept that control.', False
    if intent == 'pause':
        # Talk already paused the track. An explicit pause must cancel Talk's
        # usual automatic resume after the spoken response.
        return 'accepted', 'Music paused.', False
    return 'accepted', 'Skipping to the next song.' if intent == 'next' else 'Going back a song.', resume_after_reply
