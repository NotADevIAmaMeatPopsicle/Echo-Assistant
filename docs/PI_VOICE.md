# Talk to the Pi

The Pi can listen locally for **“Hey Echo”** or **“Okay Echo”**, play a soft cue,
capture your request, and answer through its own attached speaker. The round
Echo is not required. Wake detection runs on the Pi; local transcription, the
assistant and speech synthesis run on the shared Echo host.

## Install and select audio

Use a 64-bit Linux Pi with `alsa-utils`, Python's `venv` support, and an attached
microphone and speaker. From the copied repository, as the normal desktop user:

```bash
python3 deploy/pi/install_wake.py
python3 deploy/pi/setup.py --install
```

The first command installs pinned Vosk dependencies in an isolated user runtime
and downloads the small English model from its publisher, verifying the pinned
SHA-256 before extraction. Use `--archive PATH_TO_MODEL_ZIP` to reuse that same
verified archive offline. Runtime startup does not download models or enable
listening. The Pi bridge uses the isolated interpreter when it is installed.

On the Pi, open **Settings → Talk to this Pi**:

1. Select the attached microphone and speaker by their ALSA names.
2. Leave output at **2%** initially, and enable the local wake listener.
3. Allow spoken home controls only if wanted; existing Home Assistant grants
   still apply. The manual Talk button uses the current message's home-control
   and spoken-reply checkboxes.
4. Save, then use **Unmute this Pi** on Echo's page when ready to listen.

Listening is disabled and software-muted by default. Mute closes this listener's
capture process; it does not disconnect microphone power or mute other programs.
Settings persist across restarts. Missing selected hardware remains unavailable;
Echo does not choose another room or another sound card automatically.

## Use voice and interruption

Say a wake phrase, wait for the soft cue, then speak. A pause ends the command;
capture is capped at eight seconds. **Talk** starts a request manually, **Send
recording** ends it early, and **Cancel** stops capture, the current request or
reply playback. The display follows listening, thinking and speaking and shows
the resulting transcript and answer in the conversation.

Wake words remain active during Spotify. The default pauses music before the
warm cue. With a shared audio output, choose **Lower music by 80%** in the Pi voice
settings to keep music playing quietly through the cue, request and reply. Its
previous output level returns afterward; Spotify's volume setting is unchanged.
A cancelled request releases the reduction too. This never resumes a track that
someone paused.

Interrupting Echo's **own spoken reply** by voice still requires a selected
microphone input that already cancels speaker echo, such as a hardware DSP or OS
echo-cancelled source. Otherwise use Talk or Cancel during replies. This adapter
does not implement acoustic echo cancellation. Music or nearby speech can still
cause false wakes, especially when the microphone is close to a loud speaker;
actual room performance remains a hardware check.

In pause mode Spotify stays paused after the conversation. Browser
recording, calls and announcements take audio priority and suspend native wake
capture while they use the devices. Native capture resumes when they release
audio. The listener keeps checking its pairing and speech-host connection;
unavailable or revoked access stops capture and prevents new requests.

## Privacy and recovery

Idle microphone samples are processed locally and are not sent to the host.
Only the bounded command after activation is uploaded to the private speech
endpoint. Microphone audio and decoded replies stay in memory; reply playback
uses a Linux memory file rather than a recording on disk. The Pi retains only
the most recent transcript/result for up to two minutes to update its screen.
The browser's conversation remains in that tab until reload. Nothing here saves
full transcripts or recordings to persistent storage.

Each voice upload has its own cancellation ID. A late stop cannot cancel a newer
conversation, and a stop received before its upload prevents that capture from
starting. Requests are never automatically retried, because they may contain
home actions. Stop requests cannot undo an action already completed by the host.

## Current verification

The ARM64 Vosk runtime and pinned model load on the Pi. Synthetic Linux child
processes exercise actual capture pipes, memory-backed playback, cue and reply
flow, 2% attenuation and mute cleanup without opening ALSA hardware. Unit checks
cover wake phrase/confidence rules, capture bounds, cancellation races and muted
settings; silent browser checks cover the native state and controls.

Actual wake accuracy, microphone gain, reply audibility and echo control remain
physical acceptance. New installations keep listening disabled until their
microphone and speaker are selected and the listener is enabled.
