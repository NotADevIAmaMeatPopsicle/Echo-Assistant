# Grouped music on Echo Mini

The Mini needs timestamped audio to join the Deck's Music Assistant playback.
Firmware **0.16.0** implements that transport and its playback scheduler. Its
host sender is implemented, but the Sendspin session, owner settings and voice
bridge integration are still being connected. This is not yet an enabled Mini
player, and the new firmware has not been installed on the physical board.

The existing Mini voice, Spotify and intercom transports remain separate. No
Music Assistant account, token or discovery service is added to the firmware.
The intended adapter uses the existing authenticated USB or paired TLS wire.
The [grouped-music guide](GROUP_MUSIC.md) describes the working Deck connection.

## Timing and audio

The wire carries 48 kHz, 16-bit mono PCM, matching the Mini's attached speaker.
Each 256-sample block has a device-clock presentation time and an audio-session
identifier protected by the frame checksum. The firmware renders the sample
position due at that time, interpolates fractional positions, outputs silence
before a block is due, and skips expired audio rather than adding delay.

The host estimates device-clock offset from matching bounded round trips. It
requires three timely samples and stops sending if clock observations expire.
Linux uses the raw monotonic clock to avoid mixing NTP-slewed timing with
Sendspin's clock domain. The adapter must pass the same clock to the Sendspin SDK.

The firmware predicts DMA presentation from the existing legacy I2S driver's
eight-descriptor cycle. A missed timing observation invalidates the prediction
until eight fresh writes arrive. This preserves the existing I2S/codec setup;
it does not establish exact DAC or acoustic latency. The sender has an explicit
latency-calibration parameter for later physical measurement. No calibration
has been performed on this board.

PCM stays in bounded memory: 256 firmware blocks and at most 384 host blocks.
The host also limits unacknowledged packets to the existing USB receive window.
The output ceiling starts at 2%; firmware applies the smaller of its physical
volume setting and the group gain. Normal mute/heartbeat and transport-loss
handling still stop or disarm the appropriate existing audio paths.

## Adapter integration contract

The owning voice bridge must negotiate `timed_audio=1` before sending any new
commands. Older firmware receives none of them. The adapter must:

- Use one wire writer for timed playback, ordinary audio and controls.
- Stop the timed session before a cue, spoken reply, alarm, intercom or Spotify
  takes the speaker; discard its pending PCM while that other source has focus.
- Clear the timed session on Sendspin clear, end, disconnect or access removal.
- Resume from newly received presentation timestamps, never replay held audio.
- Bind the Music Assistant identity to the verified Mini, with an explicit owner
  enablement and a separately selected shared output.
- Report both server-clock and device-clock health, and keep registration disabled
  when the optional runtime or firmware capability is missing.

Those connection and focus hooks are **not yet installed in the voice bridge**.
Do not enable a player or claim multi-room playback from the timing core alone.

## Wire additions

| Message | Purpose |
| --- | --- |
| `GROUP_CLOCK nonce` | Return the same nonce and device monotonic microseconds. |
| `GROUP_BEGIN session ceiling` | Begin a timestamped music session; acknowledge capacity. |
| `GROUP_GAIN session level` | Change gain within that session's initial ceiling. |
| `GROUP_STOP session` | Stop only the matching timed session. |
| `RV1!` type 4 | Little-endian session ID, presentation microseconds and 512 PCM bytes, followed by CRC32. |
| `EVENT group_session=…` | Receive/consume credits, active state and missing/late counters. |

Existing type-2 PCM remains unchanged. Type-4 payloads are 524 bytes: four bytes
of session, eight bytes of presentation time and 512 bytes of audio. Both kinds
retain the existing sequence header and checksum. Wrong sessions, bad lengths,
invalid checksums, out-of-order sequence numbers and out-of-window times fail
closed. Clock probes contain no microphone or track content.

## Verification and remaining acceptance

The native C++ timing check exercises the firmware queue in memory. Python
checks cover clock expiry, focus stops, gain ceilings, frame checksums, credits,
packet boundaries and legacy sender behavior. Firmware compilation and the
four-image bundle verification pass without accessing a device.

After the full adapter is connected, use the [identity and backup checks](HARDWARE.md)
before installing. Real playback, drift over long sessions, Wi-Fi jitter, quiet
volume, voice interruption and measured timing against the Deck remain unverified.
