# Choose an Echo build

Echo separates the assistant host from the devices you speak to and hear. A device
can include its own display, microphone and speaker, or be an explicitly selected
part of a room setup. Models and integrations can stay on a more capable host.

The primary Pi build combines its touchscreen with a microphone and speaker
attached directly to the Pi. It must work without the round speaker. The round
AMOLED build remains a separate compact smart speaker.

| Build | Audio path | Current implementation and limits |
| --- | --- | --- |
| Pi smart display | Microphone and speaker attached to the Pi | Paired kiosk, push-to-talk with replies returned to that Pi, radio/files, announcements and answered display calls are implemented in software. Local wake words, Pi Spotify playback, Pi alarm routing and physical audio verification remain open. |
| Round AMOLED speaker | Onboard microphone and attached speaker | Existing firmware, host voice transport, wake words, replies and Spotify receiver. Round intercom controls and adapter remain open. |
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
2. Verify its attached audio hardware, mute behavior, wake words and interruption.
3. Extend intercom to the round speaker and document both primary assemblies.
4. Add reusable adapter guidance and device-specific acceptance for spare hardware.

The [build queue](BUILD_QUEUE.md) tracks implementation and physical acceptance.
A feature passing a simulated test is not a claim that an untested phone, sound
card or ESP32 board will work unchanged.
