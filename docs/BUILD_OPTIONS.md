# Choose an Echo build

Echo separates the assistant host from the devices you speak to and hear. A device
can include its own display, microphone and speaker, or be an explicitly selected
part of a room setup. Models and integrations can stay on a more capable host.

The primary Pi build combines its touchscreen with a microphone and speaker
attached directly to the Pi. It must work without the round speaker. The round
AMOLED build remains a separate compact smart speaker.

| Build | Audio path | Current implementation and limits |
| --- | --- | --- |
| Pi smart display | Microphone and speaker attached to the Pi | Paired kiosk, push-to-talk with replies returned to that Pi, radio/files, announcements and answered display calls are implemented in software. The Pi Spotify adapter adds a separately named ALSA receiver. Local wake detection, native replies, software mute, request interruption and alarm chimes are implemented. Playback wake needs an explicitly configured echo-cancelled input. Physical audio verification remains open. |
| Round AMOLED speaker | Onboard microphone and attached speaker | Firmware, host voice transport, wake words, replies and Spotify receiver. Answered intercom controls and a duplex host adapter are implemented; the new firmware still needs installation and physical call verification. |
| Spare phone, tablet or computer | Its browser, microphone and speakers | Responsive paired display, push-to-talk and answered calls reuse the browser path. Requires a secure connection and explicit microphone permission. Mobile background operation, continuous wake and device-specific audio performance are not verified. |
| Another Pi or ESP32 audio endpoint | Its configured input/output, with an optional separate screen | Planned adapter path. The current ESP32 firmware targets the documented Waveshare board; other boards are not plug-and-play. |

## Shared behavior

Each room endpoint should have its own revocable identity, name, input, output,
volume and mute state. The screen shows the status of its selected audio path.
Replies return to the endpoint that heard the request; announcements and calls
use explicit destinations. Missing or disconnected hardware must be reported
locally, with no automatic switch to another room's microphone or speaker.

A future split setup can pair a spare audio device with a separate screen. That
selection must be explicit and show where listening and playback happen. The
screen-to-audio pairing UI and general adapter protocol are not implemented yet.

## Build priority

1. Complete the Pi's independent voice, music and alarm paths.
2. Polish the Pi display while microphone/speaker hardware acceptance remains pending.
3. Verify its attached audio hardware, mute behavior, wake words and interruption.
4. Install and verify round intercom, then document both primary assemblies.
5. Add reusable adapter guidance and device-specific acceptance for spare hardware.

The [build queue](BUILD_QUEUE.md) tracks implementation and physical acceptance.
A feature passing a simulated test is not a claim that an untested phone, sound
card or ESP32 board will work unchanged.

Pi timer and reminder chimes use the attached speaker independently of the round
board. See [Pi alerts](PI_ALERTS.md) for output setup and delivery behavior.

[Pi voice setup](PI_VOICE.md) explains the local listener, software mute, attached
audio selection and the playback echo-control requirement.
