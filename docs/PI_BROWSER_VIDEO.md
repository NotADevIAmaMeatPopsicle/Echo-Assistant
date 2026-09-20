# Dedicated Pi browser-video audio

ECHO-09A provides a native audio admission boundary for the optional ordinary
YouTube player described in [the provider decision](VIDEO_PROVIDER_OPTIONS.md).
It does not establish Netflix, Prime, paid YouTube, DRM or actual Pi playback
support. The owner grant remains off by default; constructing this adapter does
not enable it or contact a provider.

## Owner setup and use

In owner `/display`, open **Settings → YouTube**, enter the selected ordinary
YouTube video's 11-character ID, enable it, and choose the permitted Household
displays. This ordinary embed needs no API key or OAuth setup, and Echo provides
no provider-account sign-in. On an allowed Deck, open **Music → Load selected
video**. The separate player opens muted; use YouTube's Play and unmute controls.
The native PCM cap remains 2% even if YouTube's volume is set to 100%. **Stop**
closes that player and returns to the existing kiosk.

This batch is a local software checkpoint and has not been deployed. The selected
USB audio route is currently absent. The feature remains off by default, and
loading is unavailable until the actual processed output and other checks pass.
Do not select another audio device as an automatic fallback.

## Integration contract

```python
from browser_video import BrowserVideo

receiver = BrowserVideo(home, focus_snapshot)  # Inert; injectable backend/clock.
receiver.check()                 # Explicit read-only capability probes.
receiver.start(lease_id, video_id)  # Only explicit start creates runtime children.
receiver.heartbeat(lease_id)      # State-only; never opens/reopens a stream.
receiver.hard_stop('focus')       # bool: synchronous native stop acknowledgement.
receiver.snapshot()              # Local state only; no commands/access callback.
receiver.close()                 # bool; unused adapter cleanup is inert.
```

`check()` returns `{"available": bool, "error": fixed_reason_or_null}`.
The coordinator can cache it for five seconds; successful checks do not prove
browser decoding, account entitlement, provider playback or physical audibility.
`start`, `heartbeat`, `hard_stop` and `close` return booleans. Ordinary stop
failure never escapes as an exception.

The snapshot contains `phase` (`idle`, `starting`, `playing`, `stopped`,
`unavailable`), `active`, `output_active`, `error`, `stop_confirmed`, `lease_id`,
`video_id`, and `output_volume: 2`. `playing` means the native pipeline was
admitted, not that YouTube reports playback. `output_active` is conservative:
it stays true after an unconfirmed stop. Keep lease/video values internal to the
trusted Pi bridge; public availability must filter them.

The coordinator supplies one fresh random lowercase 32-hex lease and a strictly
11-character `[A-Za-z0-9_-]` video ID after checking the owner-selected video,
Household display allowlist and profile/configuration revisions. There is no
arbitrary URL, subprocess argument, output selection or volume setting. Chromium
loads only `http://127.0.0.1:8790/display/video-player#<lease>`; the bridge maps the
lease to the authorized video. The fragment is not an HTTP Referer credential.
The player pulses every two seconds. A lease expires after 15 seconds without a
valid pulse. A used lease cannot start again, and a heartbeat never revives an
expired/stopped player. After 4,096 start attempts the adapter refuses new leases
until its service restarts; this bounds replay bookkeeping without eviction.

`focus_snapshot()` must return actual booleans `held`, `ducked`, `spotify_active`,
`access_valid`, a nonnegative integer `generation`, and monotonic `observed_at`
no more than one second old. Generation changes, hard focus, Spotify, access
loss, stale state and lease expiry stop the pipeline and latch it closed. A soft
duck multiplies the already capped level by 20%. Every subsequent start is an
explicit new request. The worker never calls the focus supplier under its lock.

Before starting, the coordinator stops Bluetooth/old video and pauses Spotify,
outside music/session locks, then refreshes authorization and focus. Group music
blocks admission. During potentially slow startup, the session access monitor
must refresh independently of `receiver.snapshot()`; startup holds the receiver
lock and performs a fresh focus check before admitting PCM. The coordinator
must call `hard_stop()` outside its locks before acknowledging capture or
starting competing output. **False blocks capture.** An iframe `PAUSED` event,
DOM removal or a YouTube volume setting is never this acknowledgement.

## Actual local route

```text
temporary Chromium profile
    -> private null-only Pulse sink
    -> that sink's monitor (stereo s16le, 48 kHz)
    -> 20 ms blocks, software gain <= 2% (0.4% when ducked)
    -> owned Python/libpulse output process, unity stream gain, DONT_MOVE
    -> existing echo_processed -> selected Echo speaker
```

The extra Pulse server loads exactly `module-native-protocol-unix` and
`module-null-sink` from a generated private script. Runtime module loading and
client-requested exit are disabled. Startup verifies that there is exactly one
null sink and its monitor, and no other modules/sources. It has no hardware
module, device discovery, network listener, microphone or connection to the
existing real Pulse server. The sole `parec` input names this null monitor.

Chromium receives a private `ALSA_CONFIG_PATH` containing only null PCM devices
and explicit null ALSA input/output flags. Pulse failure cannot fall back to a
real ALSA device. Microphone/camera/geolocation permissions are denied in the
temporary profile and permission prompts are denied. There is no debugging
port, reused browser profile, stored account, microphone capture API, automatic
loopback, global mixer change or browser sandbox-disable flag.

The final helper uses `libpulse.so.0` directly because `pacat` does not expose
`PA_STREAM_DONT_MOVE`. It connects to the fixed existing
`unix:/run/user/<uid>/echo-audio/native`, with explicit `echo_processed`, unity
per-channel gain and `DONT_MOVE`. Losing that sink fails the stream; it cannot
be rescued onto a default/HDMI sink. The helper also checks the device name and
rejects any input sample with absolute magnitude above 655, below 2% of signed
16-bit full scale. The receiver rounds attenuation toward silence. This is a
PCM amplitude ceiling, not a calibrated speaker loudness/SPL measurement.

Writes are bounded; congestion, dead children and malformed PCM fail closed.
The final Pulse queue requests 20 ms target/40 ms maximum buffering. Actual
end-to-end/hardware latency remains unmeasured. Stop kills the owned output
process first, then Chromium's process group, reader and private server; it
requires their exit and disappearance of that output PID's real Pulse sink
input. No fallback, respawn or buffered replay occurs after stop. A failed
acknowledgement retains conservative output state and blocks admission.

## Supported prerequisites and private files

- A normal Linux user, `/proc`, private owner-only `/run/user/<uid>`, and the
  existing private Echo Pulse socket with a real `module-echo-cancel`-owned
  `echo_processed`. Mere ALSA name hints or a same-named null sink do not pass.
  Flat-volume sinks are refused because setting a stream gain could otherwise
  implicitly change shared sink gain.
- Distribution PulseAudio **16.1 or 17.0**, `pulseaudio-utils` (`pactl` JSON and
  `parec`), `libpulse0` (`libpulse.so.0`), Python 3 and Chromium
  (`chromium` or `chromium-browser`). No Bluetooth module dependency. PipeWire
  emulation or unrecognized server versions report unavailable.
- Existing X11 session and `xrandr`. Use `DISPLAY`, defaulting to `:0`, and
  `XAUTHORITY`, defaulting to `<home>/.Xauthority`. Geometry comes from
  `kiosk.x11_geometry`; the dedicated child uses explicit X11 bounds so a bare
  session needs no window manager. The existing kiosk stays running beneath it.
  Wayland-only sessions are not implemented by this adapter.

Only an explicit start allocates `/run/user/<uid>/echo-video-<random>` at mode
0700. Generated Pulse/ALSA configuration and Chromium preferences are mode
0600. The browser profile, cache and Pulse state are temporary beneath that
directory; successful stop removes only that exact owned directory. The process
environment changes apply to these children, not the kiosk or host. Chromium's
own browser/decoder memory and profile cache use are additional to the small PCM
buffers and remain workload-dependent; Pi resource/thermal behavior needs real
acceptance. There is no new IP port; only a private Unix socket. YouTube network
egress begins when the authorized player loads its iframe and remains governed
by the provider/privacy decision, not by the null audio server.

This implementation installs nothing and changes no services. Missing packages,
X11 or processed audio are unavailable reasons, not triggers to install, enable,
change devices or fall back. The currently absent selected USB audio hardware
must be restored through the existing audio setup before this check can pass.
Bundle `browser_video.py`, `browser_video_backend.py` and the existing `kiosk.py`;
the backend launches its own fixed `--pcm-output` entry point, not another file.

## Validation and remaining acceptance

Run `python -m unittest discover -s tests -p test_pi_browser_video.py`.
The 34 synthetic tests cover lease replay/expiry, stale focus/access, competing
playback, post-start recheck, stop/start races, PCM framing/cap/duck, sanitized
errors, native explicit sink/unity/DONT_MOVE arguments, sink loss and process plus
Pulse-stream stop acknowledgement. Compile checks passed on the development
host. These tests open no microphone, real output, provider page or OS service.

Two additional tests in `tests/test_pi_browser_video_linux.py` are restricted to
an explicitly opted-in Docker container with no `/dev/snd`. They exercise real
libpulse sink removal/no fallback and the private server/monitor/output pipeline
with digital silence, a fake browser process and real stop cleanup. Both pass
against the corrected source on Debian 12/PulseAudio 16.1, with no skipped tests.
The original attempt was interrupted by a host disk-full incident. After host
recovery, the tests exposed actual PulseAudio format differences: module JSON
omits numeric IDs, and source JSON names its sink using `monitor_source`.
The backend now reads explicit module IDs from the short listing and validates
both sides of the null monitor relationship plus driver and module ownership.
Production output still requires the existing echo-cancellation sink.

The final Linux image passed 114 integration tests and both real null-audio tests
with no skips. Host and Pi integration is deployed, with settings and pairing
preserved and video disabled. Run the Linux checks in a disposable container with
no network, published ports, hardware devices or host mounts. No real browser,
recording or physical playback is part of these checks. Real acceptance must still cover ordinary YouTube touch and
captions, its correct Referer/client identification, no-signal/error states,
2%/duck behavior, Stop/voice/access revoke, selected-sink loss, returning to the
kiosk, and no resume after service/browser/network failure. This work does not
close ECHO-09 or the missing-hardware ECHO-13 gate.

Primary implementation references: PulseAudio 17.0 [stream flags](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/pulse/def.h),
[stream API](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/pulse/stream.h),
[pacat options](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/utils/pacat.c),
and [daemon startup](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/daemon/main.c)
(module loading is disabled after the startup script runs).
