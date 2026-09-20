# Grouped music on Echo Mini

The Mini needs timestamped audio to join the Deck's Music Assistant playback.
Firmware **0.16.0** implements that transport and its playback scheduler. The host
now includes the Sendspin session, owner settings, music controls and voice-priority
integration. The receiver defaults to **disabled**. The matching firmware has not
been installed on the physical board, so real Mini playback is still unverified.

The existing Mini voice, Spotify and intercom transports remain separate. No
Music Assistant account, token or discovery service is added to the firmware.
The adapter uses the existing identity-verified USB or paired TLS wire.
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

## Enable the Mini

1. Verify the board identity and original backup before installing firmware
   0.16.0, following [the hardware guide](HARDWARE.md). Older firmware receives
   no new group-audio commands and does not register a player.
2. Use the current Docker host image, which includes the optional SDK. For a
   Windows AMD64 host using Python 3.14, install into Echo's existing virtual
   environment with `python -m pip install --require-hashes --only-binary=:all:
   -r config/group-music-host.lock.txt`. The same lock supports Linux AMD64/Python
   3.13. Other architectures require a separately reviewed wheel lock.
3. Connect the private Music Assistant server in **Settings → Music Assistant →
   Connection & outputs**. Under **Echo Mini**, enable the receiver, choose its
   name, and leave the speaker ceiling at 2% initially. Save the connection.
4. Wait for the Mini to connect, then **Load outputs**, select its registered
   output, and **Save shared outputs**. Also share any outputs it will join.
5. Use **Music → Together** to select a source and compatible rooms. Playback
   or reconnecting to an existing Music Assistant session can start sound, so
   perform initial acceptance at a comfortable volume.

The owner page reports missing firmware/runtime, connection and clock readiness.
The host resolves Music Assistant's canonical player using its reported Sendspin
protocol identity, rather than its display name. Mini play/skip buttons and basic
voice music commands target that player after a group stream selects it. They
check the shared-output permissions again before sending a control. Microphone
mute is independent of music volume; the physical volume setting still limits
the amplifier output. Calibration accepts ±200 ms; leave it at zero until measured.

## Voice and connection behavior

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

Those hooks are installed in the voice bridge. A separate bounded network worker
receives raw mono PCM and metadata; only the voice thread writes to the board.
It keeps the server clock running during local voice interruptions, discards
held audio and resumes at fresh timestamps. Other group members are not paused
by a local cue or reply. An explicit pause/skip command controls the shared group.
Spotify has priority when it is playing on this Mini.

Saved owner settings are checked twice per second. Disabling the receiver,
changing the server or losing firmware capability closes its connection. Missing
SDK dependencies leave ordinary voice/Spotify usable. Health stores counters and
clock/focus state, with no audio, track history, account token or device identity.
The SDK uses only player and metadata roles; no controller role, discovery
listener or new inbound port is enabled.

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

The native C++ timing check exercises the firmware queue in memory. Python checks
cover clock expiry, focus stops, gain ceilings, frame checksums, credits, packet
boundaries, access removal, shared-output checks and legacy sender behavior. The
actual pinned SDK also connects to a synthetic loopback server, negotiates mono
PCM, synchronizes time, passes synthetic samples to the fake wire, handles clear
and disconnect, and rejects redirects before forwarding credentials. These
checks pass on Windows and isolated Linux without any audio devices or live
services. Firmware compilation and four-image bundle verification pass separately.

Use the [identity and backup checks](HARDWARE.md) before installing. Real playback,
drift over long sessions, Wi-Fi jitter, quiet
volume, voice interruption and measured timing against the Deck remain unverified.
