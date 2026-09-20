# ECHO-08: phone audio receiver decision

Research checked **2026-09-20**, against repository baseline **6f770b1**. This is
the wave-2 provider gate, not an installed receiver or a completed ECHO-08.
No Pi connection, installation, configuration change, pairing or playback was
performed. The intended sender is **Spotify Premium on a Pixel 9 Pro XL**. The
Pi 4B touchscreen is Deck; the ESP32-S3 Mini remains an independent endpoint.

## Decision

**Implementation update:** ECHO-08A's default-off adapter and shared audio-focus
integration are now in the Pi bundle. See [Bluetooth setup](PI_BLUETOOTH.md) for
the actual supported prerequisites and limitations. The research below records
the decision; phone configuration and physical playback remain unverified.

Keep the working Pi Spotify Connect receiver for Spotify's device picker.
Implement one additional, **default-off Bluetooth Classic A2DP receive adapter**
for audio playing on the owner's Pixel. Use the Pi's BlueZ and existing private
PulseAudio service, subject to the read-only inventory gate below. This adds a
normal Bluetooth speaker destination without requiring another Android media
app, a LAN receiver or a new cloud account. Spotify explicitly supports playback
to Bluetooth speakers; Pixel documentation distinguishes **Media audio** from
**Phone audio**. This task supports media only. [1][2]

This is **Bluetooth audio**, not Chromecast, screen mirroring, a phone-call
endpoint, lossless playback or synchronized multiroom audio. Do not add a Cast
badge. Commercial-video playback and DRM remain ECHO-09. Bluetooth transports
audio that the phone/app permits to play; it does not authorize or render a
commercial video service on Deck.

## Verified choices and sender fit

| Route | Receiver evidence and version | Pixel / Spotify fit | Decision |
| --- | --- | --- | --- |
| Existing Spotify Connect | Repository pins **librespot 0.8.0**; Pi ARM64 adapter already exists. MIT upstream; retain existing notices. Spotify describes Connect as one device controlling listening on another. [3] | Native Spotify app; Premium is required by this adapter. Owner already confirmed initial Pi playback. Later echo-processing acceptance remains separate. | Preserve; no second Spotify implementation. |
| Bluetooth A2DP | PulseAudio explicitly supports both A2DP roles. **BlueZ 5.87**, released archive dated **2026-07-03**, is the newest 5.x archive observed; use distribution packages, not a source upgrade. PulseAudio **16.1 / 17.0** code supports the needed BlueZ discovery options. [4][5][6] | Android routes Spotify and other permitted media to a paired audio device; no extra sender app. Pixel remains responsible for decoding, connectivity and battery use. | **Implement next**, with bounded admission and PCM output gating. |
| Shairport Sync / AirPlay | Maintained Linux **audio receiver**; **5.5.2**, released **2026-09-14**, fixes Apple OS 27 compatibility. MIT main code plus bundled notices/dependencies. AirPlay 1 or 2 build; audio only, no AirPlay video/photos. [7] | Apple devices and compatible AirPlay senders are documented. A native Pixel Spotify-to-AirPlay path was not established; an additional Android sender would only help its supported media. | Valid future Apple use case; does not solve this sender requirement. |
| gmrender-resurrect / UPnP AV | Maintained headless **renderer**, **0.3.1**, released **2026-02-13**. GPL-2.0-or-later; GStreamer and libupnp dependencies. Upstream explicitly states that its low commit rate does not mean abandonment. [8] | Upstream compatibility list includes Android **BubbleUPnP** and **Hi-Fi Cast**, which act as controllers and can serve supported media. A renderer does not make Spotify's native Android app a DLNA sender or provide its protected stream. | Real option for local files/radio through another app; unnecessary for Spotify/Pixel Bluetooth. |
| upmpdcli / UPnP + OpenHome | Maintained **MPD renderer front end**, **1.9.18**, release **2026-09-11**; GPL per upstream, with MPD/libnpupnp/libupnpp and other dependencies. [9] | BubbleUPnP/OpenHome controllers; MPD does playback. Upstream's Spotify/Songcast example is forwarding from Windows/Mac with supplemental software, not native Pixel Spotify support. | More components for a different use case; no implementation now. |
| Official Google Cast | Google's Web Receiver is an HTML5/JS application **running on a Cast-enabled device**; Android TV receiver support likewise requires that platform. Hosting a receiver page or opening it in Pi Chromium does not create that device. [10] | Spotify/Pixel can control supported Cast receivers. No official generic Raspberry Pi OS/Linux receiver package or supported licensing route was established. | Do not promise a software Chromecast. If native Cast is essential, select a supported external Cast device as a separate product decision. |

Home Assistant speaker control and **PyChromecast are controllers**, not receiver
implementations. PyChromecast's own description is discovery/control of existing
Chromecasts and launching their receiver apps. Installing it cannot make Deck
appear as a Chromecast. Likewise, a DLNA media server is not a renderer. [11]

## Package and resource evidence

The repository proves an ARM64 Pi deployment and installed Echo PulseAudio AEC
route, but does **not** identify the currently installed OS release or exact
BlueZ/PulseAudio versions. Debian availability below is evidence of maintained
ARM64 packages, not an inventory of this Pi or a promise about its configured
Raspberry Pi OS repositories. Do not mix Bookworm and Trixie packages.

| Distribution package observed | ARM64 version on 2026-09-20 | Package-only installed size |
| --- | --- | --- |
| Debian Trixie `bluez` | **5.82-1.1** | 5,566 kB |
| Debian Trixie `pulseaudio-module-bluetooth` | **17.0+dfsg1-2+b1** | 515 kB |
| Debian Bookworm `pulseaudio-module-bluetooth` | **16.1+dfsg1-2+b1** | 511 kB |
| Debian Trixie `shairport-sync` | **4.3.7-1** | 722 kB |
| Debian Trixie `gmediarender` | **0.3-1** | 206 kB |

These sizes exclude dependencies and runtime memory. The PulseAudio module must
match its distribution server package exactly. Trixie's `upmpdcli` package URL
returned **No such package**; upstream installation routes are separate. Debian's
Shairport/gmediarender versions trail the observed upstream releases. [12]

BlueZ's daemon is GPL-2.0-or-later. PulseAudio source is generally LGPL-2.1-or-later,
with optional GPL dependencies affecting the built server/modules; preserve the
distribution copyright files and upstream notices rather than labeling the
whole stack MIT. No proprietary Bluetooth codec is needed for the initial SBC
route. Other codec availability is build/device dependent. [6][13]

No source provides a useful measured RAM/CPU minimum for this exact combined
Echo workload. Shairport specifies a Raspberry Pi B or better; gmrender targets
small headless Pi-class machines; upmpdcli adds a separate MPD process. Bluetooth
adds SBC decoding and one gated PCM pump to the existing audio server. Stereo
16-bit/48 kHz PCM is **192,000 bytes/s**; a 250 ms application buffer is **48 kB**
(calculated, excluding PulseAudio/BlueZ buffers). Set a bounded buffer and measure
CPU, memory, underruns and temperature during later physical acceptance. Do not
infer those results from package sizes or the Pi 4 recommendation of 4 GB RAM.

## Network, privacy and focus implications

| Route | Connections / discovery | Required Echo integration |
| --- | --- | --- |
| Bluetooth | Bluetooth radio plus BlueZ system D-Bus and private PulseAudio Unix socket; **no new IP listening port, mDNS or SSDP**. BlueZ persists bond keys/device identity in its protected OS storage. Phone apps keep their normal network behavior. | One owner-approved bonded phone; only its A2DP media source may feed PCM. Preserve 2% local ceiling, 80% ducking and hard focus holds. No microphone route to the phone. |
| Shairport | mDNS UDP 5353; upstream defaults TCP 5000 for AirPlay 1 or TCP 7000 for AirPlay 2. AirPlay 1 allocates UDP from 6001 with a default range of 10. AirPlay 2 additionally needs negotiated media/control sockets and NQPTP UDP 319/320; this is not an exhaustive AirPlay 2 firewall recipe. [7][14] | LAN interface/password/admission decisions and a focus/output adapter. D-Bus/MPRIS metadata exists; upstream stable remote playback controls are limited to classic AirPlay. Do not assume a reliable pause acknowledgement for AirPlay 2. |
| UPnP renderers | SSDP UDP 1900 multicast plus HTTP description/control/event endpoints and outbound media fetches. gmrender defaults TCP **49494** and supports explicit interface/port selection. upmpdcli also needs its local MPD control connection. [8][9] | LAN control/admission policy, a bounded URI fetch policy, metadata privacy, output attenuation and focus interruption. Discovery is not owner authorization; never expose these endpoints through the owner UI gateway as a shortcut. |
| Official Cast | Requires a supported Cast endpoint and that product's network/service behavior. | No Pi receiver is proposed; adding sender/control code does not satisfy ECHO-08. |

Bluetooth pairing is a new, separate media permission; it must not grant Echo,
Hermes, calendar, household or Personal access. Keep
[the owner/device tailnet allowlist](TAILNET_ACCESS.md) unchanged. Do not add
public routes, Funnel, broad firewall rules, Bluetooth PAN, a TCP PulseAudio
server, oFono, microphone forwarding, default-device switching or automatic
discovery/pairing. Track titles, artwork and listening history are unnecessary
for this first adapter. Status may expose a sanitized owner-chosen device label;
addresses, bond keys and pairing confirmations must stay out of logs/browser
storage/Git. A bonded phone is authorized through the Bluetooth policy, not by
being on the same tailnet.

## Existing Pi contract: inspected read-only

- [`setup_echo_audio.py`](../deploy/pi/setup_echo_audio.py) generates the private
  `echo-audio.service`, using
  `unix:/run/user/<uid>/echo-audio/native`, `echo_processed` speaker and
  `echo_cancelled` microphone. Its configuration loads neither Bluetooth
  discovery nor a network listener. The current receiver cannot work merely
  because Bluetooth hardware or the `bluez` package exists.
- [`spotify.py`](../deploy/pi/spotify.py) owns 15-second renewable focus and duck
  leases. `focus(client, True)` closes output and queues a pause; release does
  not auto-resume. `duck(client, True)` reduces amplitude to 20% with roughly a
  120 ms fade. `scaled_pcm()` supplies linear bounded PCM attenuation. Client IDs
  are 32 hex characters; at most 32 leases exist for each kind.
- [`listener.py`](../deploy/pi/listener.py) renews native voice focus;
  [`alerts.py`](../deploy/pi/alerts.py) uses hard holds. Browser calls and capture
  use the bridge's `/v1/display/music/focus` route.
- [`bridge.py`](../deploy/pi/bridge.py) exposes a loopback group-focus snapshot
  `{held, ducked, other_music}`. Currently `other_music` means the local Spotify
  output process is alive. [`sendspin_player.py`](../deploy/pi/sendspin_player.py)
  uses that snapshot and fails silent when it cannot refresh it. Bluetooth must
  join this arbitration; otherwise it could mix with grouped playback or bypass
  a voice/call hold.

Raspberry Pi OS Bookworm introduced PipeWire as the desktop default, and current
WirePlumber supports both `a2dp_sink` and `a2dp_source`. That does not change this
deployment's recorded private PulseAudio design. Do not install another sound
server, change desktop defaults, mask services or migrate Echo to PipeWire for
this task. A conflicting active Bluetooth/audio manager makes the preflight
unsupported until the owner chooses an integration. [15]

**Role-name trap:** Deck is the Bluetooth **A2DP Sink** and Pixel is the
Bluetooth **A2DP Source**. PulseAudio exposes received Bluetooth audio as a
recordable **source**, commonly with the remote device's `a2dp_source` profile.
Do not select `a2dp_sink` blindly and build a transmitter to headphones. [4]

## One bounded implementation task: ECHO-08A

Deliver a disabled **owner-configured A2DP audio adapter**, its read-only
preflight, private configuration and synthetic tests. No pairing UI, track
browser, extra protocol, Mini change or OS installation in this task. Keep any
real setup/enable/playback as a separate explicit deployment/acceptance step.

1. **Read-only preflight.** Report OS/architecture, installed/candidate package
   versions, `bluetoothd`/adapter status, rfkill, BlueZ D-Bus access, other audio
   managers, the actual Echo PulseAudio server version, available Bluetooth
   modules and `echo_processed`. Inspect only; no scan, connect, power-on,
   package refresh/install, module load or mixer action. Store detailed evidence
   privately; public status must not contain device addresses. Require a matched
   PulseAudio/module package and a single selected adapter.
2. **Admission and optional service.** Add a receiver using a pre-existing,
   explicitly owner-selected bond, private config defaulting to
   `{enabled:false, output:"echo_processed", volume:2}` and an opaque local peer
   reference. OS pairing remains an owner operation. Do not trust all devices,
   make the adapter permanently discoverable, auto-pair, power it on, disconnect
   unrelated devices or replace the system default pairing agent. Reject
   unselected input before creating any playback stream.
3. **Explicit audio path.** After separately authorized setup, load only the
   required BlueZ discovery module into Echo's existing private PulseAudio
   server. Read PCM only from the selected phone's actual A2DP source, normalize
   to bounded stereo s16/48 kHz, apply local attenuation/ducking, and write only
   to `echo_processed`. Disable peer absolute-volume synchronization. Never
   load `module-bluetooth-policy` or an automatic loopback: those can create
   routes outside the PCM gate. No input may be `echo_cancelled`, a monitor or
   the default source. Missing devices fail closed.
4. **Focus and lifecycle.** Spotify takes precedence over Bluetooth; Bluetooth
   takes precedence over grouped music on this Pi only. Existing hard holds
   silence/close Bluetooth output before capture is admitted. Discard pending
   PCM on holds, access failure, source change, disconnect or restart. A hard
   hold latches pause until a fresh explicit sender/local resume; lease expiry
   must not replay audio. A duck lease preserves transport and applies 20% of
   the unchanged local ceiling. Loss of permission/focus evidence fails silent.

PulseAudio 16.1 and 17.0 expose
`enable_native_hsp_hs`, `enable_native_hfp_hf` and `avrcp_absolute_volume` options.
Do **not** describe the stock module as advertising only A2DP: its native backend
also contains gateway-profile registration. Disable the phone/headset roles and
peer volume synchronization, select only A2DP, and verify the actual advertised
profiles and rejected non-media connections before deployment. No code path may
bridge Echo microphone data to any Bluetooth profile. If the installed stack
cannot enforce that boundary without global changes, report unsupported rather
than enabling it. No new receiver process should acquire microphone access. [6]

### Proposed interfaces and coordinator-owned edits

New `deploy/pi/bluetooth_receiver.py` should expose an injectable
`BluetoothReceiver(config, focus_snapshot, bluez, pulse, clock)` with
`check()`, `snapshot()`, `start()`, `disconnect_selected()` and `close()`.
`check()` is read-only; construction and disabled startup have no audio/BlueZ
side effects. `snapshot()` returns bounded `phase`, `supported`, `connected`,
`output_active`, `blocked_reason` and a sanitized label. Phases distinguish
`disabled`, `unsupported`, `ready`, `receiving`, `held` and `unavailable`.
No method accepts arbitrary PulseAudio names, shell text, URLs or Bluetooth
addresses from an unauthenticated request.

The coordinator owns these shared integration changes:

- Provide `focus_snapshot()` under the existing music lock with
  `{held, ducked, spotify_active, access_valid, generation}`. Refresh continuously
  and bound its age. Use a synchronous hard-stop acknowledgement for a new hold;
  polling alone cannot establish pause-before-microphone. Bluetooth playback
  must not hold its own permanent `music.focus` lease and thereby silence itself.
- Extend group-focus `other_music` to include Bluetooth's admitted active output.
  Preserve Spotify, listener, alerts and browser focus behavior. Do not resume a
  different endpoint or cancel another device's stream.
- Register lifecycle shutdown/revocation handling and package the new file in
  the Pi bundle. Existing pairing/host access validation must be fresh before
  enable and while receiving; an unavailable host closes this optional route.
- Keep enable/configuration owner-only. Existing local Spotify setup permits a
  Household display; copying that authorization would broaden this task's
  owner-only grant. Initial configuration can remain a private owner CLI. Any
  later HTTP setup route needs a separate owner-authorized command, not a new
  allowance for every paired display. A read-only status view must not expose
  peer identifiers or manufacture an owner session.

Synthetic checks must cover disabled side effects, wrong/unbonded peer rejection,
profile/source rejection, exact 2% PCM cap and 80% ducking, phone volume at maximum,
hard-hold acknowledgement, stale access/focus, output disappearance, disconnect,
process failure, source-generation change and no buffered replay. Tests must not
open audio hardware or change BlueZ/OS state. Report required dependencies and
configuration as a plan; do not auto-install them.

ECHO-08 remains open until an explicitly authorized real Pixel pairing/playback
check confirms SBC/A2DP, phone pause/resume, unchanged 2% ceiling, wake/call/alert
focus, AEC routing, rejection of another phone/non-media profile, and clean
disable/restart without auto-replay. Successful service startup is insufficient.

## Primary sources

All links below were fetched during this research. Release dates/versions are
observed evidence, not floating installation pins. Ignored local evidence under
`output/casting-research/` contains source responses and a SHA-256 manifest.

1. Spotify, [Bluetooth help](https://support.spotify.com/us/article/bluetooth/).
2. Google Pixel, [Bluetooth troubleshooting and Media audio](https://support.google.com/pixelphone/answer/7334382?hl=en).
3. Spotify, [Connect](https://support.spotify.com/us/article/spotify-connect/); repository [Pi receiver](PI_SPOTIFY.md), [music](MUSIC.md) and [recorded acceptance](BUILD_QUEUE.md).
4. PulseAudio, [Bluetooth roles](https://www.freedesktop.org/wiki/Software/PulseAudio/Documentation/User/Bluetooth/). Its codec paragraph is historical; it is used here for role semantics, not a claim that modern PulseAudio supports only SBC.
5. BlueZ, [official release archives](https://www.kernel.org/pub/linux/bluetooth/).
6. PulseAudio [16.1 discovery implementation](https://github.com/pulseaudio/pulseaudio/blob/v16.1/src/modules/bluetooth/module-bluez5-discover.c), [17.0 discovery implementation](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/modules/bluetooth/module-bluez5-discover.c), [17.0 role matching](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/modules/bluetooth/bluez5-util.c), and [native profile registration](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/modules/bluetooth/backend-native.c).
7. Shairport Sync [5.5.2 release](https://github.com/mikebrady/shairport-sync/releases/tag/5.5.2), [versioned capabilities/resources](https://github.com/mikebrady/shairport-sync/blob/5.5.2/README.md), [licenses](https://github.com/mikebrady/shairport-sync/blob/5.5.2/LICENSES), and [configuration](https://github.com/mikebrady/shairport-sync/blob/master/scripts/shairport-sync.conf).
8. gmrender-resurrect [0.3.1 release](https://github.com/hzeller/gmrender-resurrect/releases/tag/v0.3.1), [project status](https://github.com/hzeller/gmrender-resurrect/blob/master/README.md), [Android compatibility](https://github.com/hzeller/gmrender-resurrect/wiki/Compatibility), [dependencies/output](https://github.com/hzeller/gmrender-resurrect/blob/v0.3.1/INSTALL.md), and [license/interface/port](https://github.com/hzeller/gmrender-resurrect/blob/v0.3.1/src/main.c).
9. upmpdcli [architecture/license](https://www.lesbonscomptes.com/upmpdcli/) and [release history](https://www.lesbonscomptes.com/upmpdcli/pages/releases.html).
10. Google Cast [overview and supported receiver platforms](https://developers.google.com/cast/docs/overview) and [Web Receiver](https://developers.google.com/cast/docs/web_receiver).
11. [PyChromecast project description](https://github.com/home-assistant-libs/pychromecast/blob/master/README.rst).
12. Debian packages: Trixie [BlueZ](https://packages.debian.org/trixie/bluez), [PulseAudio Bluetooth](https://packages.debian.org/trixie/pulseaudio-module-bluetooth), [Shairport](https://packages.debian.org/trixie/shairport-sync), [gmediarender](https://packages.debian.org/trixie/gmediarender), [missing upmpdcli](https://packages.debian.org/trixie/upmpdcli); Bookworm [PulseAudio Bluetooth](https://packages.debian.org/bookworm/pulseaudio-module-bluetooth).
13. [BlueZ daemon SPDX](https://github.com/bluez/bluez/blob/5.82/src/main.c), [PulseAudio license qualifications](https://github.com/pulseaudio/pulseaudio/blob/v17.0/LICENSE), and [BlueZ Device API](https://github.com/bluez/bluez/blob/5.82/doc/org.bluez.Device.rst).
14. [NQPTP timing ports/privileges](https://github.com/mikebrady/nqptp/blob/main/README.md).
15. Raspberry Pi, [Bookworm audio migration](https://www.raspberrypi.com/news/bookworm-the-new-version-of-raspberry-pi-os/); WirePlumber [Bluetooth roles, codecs and session ownership](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html).
