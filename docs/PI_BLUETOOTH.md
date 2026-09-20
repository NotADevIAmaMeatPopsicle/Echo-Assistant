# Optional Bluetooth media on Deck

ECHO-08A implements a **default-off Bluetooth Classic A2DP receiver adapter** for
the Pi touchscreen. It reads media from one owner-selected, already bonded phone
and sends attenuated PCM through the existing `echo_processed` speaker. It is
independent of Mini and preserves the existing Spotify Connect route.

The receiver is installed disabled. Its matching distribution Bluetooth module
and SBC library are now installed on the reference Deck. The module is not
loaded, the radio remains blocked, and no phone is selected or paired by Echo.
Actual A2DP profile compatibility and phone playback remain unverified;
ECHO-08 stays open.
[The provider decision](CASTING_OPTIONS.md) explains Chromecast/AirPlay limits.

## Read-only preflight

On the Pi, the normal Echo user can inspect without a configured phone:

```bash
python3 tools/check_pi_bluetooth.py
```

After the owner has supplied a private configuration, inspect that selection:

```bash
python3 tools/check_pi_bluetooth.py --config ~/.config/echo-display/bluetooth.json
```

This reads the local apt cache, installed package versions, OS/architecture,
rfkill, user-service state, BlueZ objects and the private PulseAudio server.
It does not refresh packages, load modules, scan, pair/connect, power on the
adapter, record or play audio. Exit 0 means the inspected prerequisites passed;
exit 1 reports a bounded reason. Output omits device addresses, aliases, D-Bus
paths, raw provider errors and credentials. No file is created or repaired.
Missing phone selection or an unprepared server is an expected failure.

## Supported backend and preparation boundary

The backend uses Python's standard library and distribution commands:

- `bluez` with `org.bluez.Device1.Bonded` and `MediaTransport1` properties;
  Debian Trixie's observed package is 5.82-1.1. A stack unable to prove a
  persisted bond is unsupported. No fallback to `Trusted` or a remembered name.
- `systemd` / `busctl` with JSON ObjectManager output; `systemctl` and
  `dpkg-query` inspect current configuration.
- **PulseAudio 16.1 or 17.0**, with exactly matching distribution versions of
  `pulseaudio` and `pulseaudio-module-bluetooth`.
- `pulseaudio-utils`: `pactl` JSON lists, `parec` and `pacat`. Audio stays on
  `unix:/run/user/<uid>/echo-audio/native`; the socket directory must belong to
  the current non-root user and deny group/other access.

PulseAudio already needs the existing Echo WebRTC setup from
[PI_ECHO_AUDIO.md](PI_ECHO_AUDIO.md). This adapter refuses PipeWire's PulseAudio
emulation, an active competing user audio manager, a mismatched module package,
an absent `echo_processed` AEC sink, or unsafe routing modules. It does not
install, mask or migrate any audio service.

After a separately authorized setup, the private PulseAudio server would need
one `module-bluez5-discover` instance with these explicit arguments:

```text
headset=native enable_native_hsp_hs=false enable_native_hfp_hf=false avrcp_absolute_volume=false
```

There must be no `module-bluetooth-policy`, automatic `module-loopback`, TCP
PulseAudio listener or tunnel. Do not paste a desktop Bluetooth recipe into this
server: automatic policy can create speaker and microphone routes outside Echo's
PCM gate. The adapter never loads or unloads a module itself.

These flags do **not** mean the stock module advertises only A2DP; PulseAudio
also contains gateway-profile registration. This adapter admits only the selected
phone's SBC A2DP transport/source and fails silent if its transport/profile
changes. It does not reconfigure BlueZ advertisements or enforce radio-wide
admission for other OS clients. Any requirement to reject non-media radio
connections globally remains a separate platform acceptance gate. No receiver
code opens a microphone/default/monitor source or forwards microphone PCM.

## Owner configuration

The coordinator loads the existing private file
`~/.config/echo-display/bluetooth.json`; absent files use disabled defaults.
The file must be a regular current-user file with mode **0600**, at most 4 KiB.
Symlinks, invalid schema, another owner or broad permissions are rejected without
changing the original. The schema is exact:

```json
{
  "version": 1,
  "enabled": false,
  "adapter": "hci0",
  "device_path": "",
  "output": "echo_processed",
  "volume": 2
}
```

Only an explicit owner setup may replace `device_path` with the selected existing
bond's `/org/bluez/hciN/dev_XX_XX_XX_XX_XX_XX` path and enable the feature. The
adapter name and path must agree. Neither a new bond nor owner permission is
inferred from discovering a phone. The output and 2% local ceiling are fixed.
Do not save actual peer paths, bond keys or this configuration in Git.

Pairing remains an explicit owner OS operation outside this adapter. On Pixel,
select **Media audio** for the bonded device; phone calls are outside this task.
No automatic pairing, permanent discovery, radio power change, trust change,
default pairing agent, Bluetooth PAN or new IP port is added. Existing tailnet
and owner UI restrictions remain unchanged. A bond grants media reception only.

## Coordinator integration contract

```python
from bluetooth_receiver import BluetoothReceiver, DEFAULT_CONFIG, load_private_config

config = load_private_config(path) if path.exists() else dict(DEFAULT_CONFIG)
receiver = BluetoothReceiver(config, focus_snapshot)
receiver.start()
```

An invalid existing file must leave the feature disabled with a visible bounded
error. Bundle `bluetooth_receiver.py` and `bluetooth_backend.py`. Construction and
disabled `start()` perform no commands or audio/BlueZ operations. No setup route
or UI enable control is supplied here; a paired Household display is not
automatically an owner configuration authority.

`focus_snapshot()` is called outside the receiver lock and returns:

```text
held: bool, ducked: bool, spotify_active: bool, access_valid: bool,
generation: nonnegative int, observed_at: monotonic seconds
```

The snapshot must be at most **1 second** old, with fresh access validation tied
to this display's current credential/grant. Failed, expired, future-dated or
malformed evidence closes output. Permission generation changes also latch a
stop. `snapshot()` only reads state and never invokes the focus callback; it
contains no provider identifiers. Group focus must include its `output_active`
flag in `other_music`, including a conservatively active unconfirmed stop.

**Synchronous hard holds:** publish the hold, release Spotify's lock, then call
`receiver.hard_stop(reason="focus")` before acknowledging capture/call/alert
admission. Only `True` permits capture: it means the output process has exited
and the private Pulse server no longer reports its sink input. `False` blocks
capture. Spotify start likewise stops Bluetooth before its output starts, then
rechecks its own generation/focus. Access revocation and shutdown call hard stop.
Never call hard stop while holding Spotify's lock; the pump uses that lock via
the external snapshot callback. Polling is an additional fail-safe, not a
substitute for this synchronous acknowledgement.

`hard_stop()` accepts `focus`, `access`, `spotify`, `shutdown` or `disconnect`.
`disconnect_selected()` first stops local output, then requests **Disconnect only
for the selected existing bond**; it neither unpairs nor touches another device.
`close()` stops output/readers and joins the worker. Closed instances cannot be
restarted. A failed stop remains visible and conservatively holds group output.

## Audio and resume behavior

Deck is Bluetooth **A2DP Sink**. PulseAudio exposes incoming audio as a source
under the remote **`a2dp_source`** profile. The adapter joins that source to the
selected BlueZ card/path, checks SBC, rejects monitor/microphone/default sources,
and tracks source index/module identity. `parec` converts only that source to
stereo signed-16 PCM at 48 kHz; `pacat` writes only to `echo_processed`.

Each application read/write is at most 20 ms (3,840 bytes), with at most three
partial-frame bytes retained. Output congestion, process failure, disappearance
or a source identity change closes output and discards queued input. Restarting
a reader creates a fresh recording stream, so old pipe/server data is not replayed.
The Pulse streams request 40 ms latency; actual hardware latency is unverified.

PCM amplitude is capped at **2%** after decoding, independent of the phone's
volume. A duck lease uses **0.4%**, exactly 20% of that ceiling; releasing just
a duck restores 2%. The adapter does not change sink/hardware mixer volume.
The output stream is explicitly unity gain; existing speaker/amplifier gain
remains the owner's physical setting. Initial SBC support makes no lossless,
codec-upgrade, video-sync, call or multiroom claim.

A hard hold or stale permission latches silence. Expiry/release never resumes
automatically. The adapter must observe the connected phone's selected transport
become idle or disappear, then newly stream (`pending` or `active`) after the hold.
Radio disconnection/reconnection alone never authorizes resume. If a phone
keeps its transport active while paused, that is insufficient evidence; use a
separate explicit owner `receiver.resume()` action after focus/access clears.
That method does not send Play to the phone. Initial startup with an already
active stream also waits for fresh sender action; a source-generation change
requires another fresh action. Bluetooth never pauses or resumes Mini.

## Verification and remaining acceptance

Run the focused synthetic suite with:

```bash
python -m unittest discover -s tests -p test_pi_bluetooth.py
```

The suite substitutes command/process/audio boundaries and exercises the actual
selection, state machine, PCM attenuation and command construction. It must not
open an audio device, change BlueZ or connect to a live provider. Physical
acceptance still requires separately authorized module/package setup, the actual
Pixel bond, quiet media playback, phone volume maximum at the unchanged local
ceiling, hard/duck focus, Spotify/group priority, AEC, source/profile rejection,
disconnect, disable and cold restart without replay. Software completion alone
does not close ECHO-08.

The implementation checkpoint passed **27 focused checks on Windows**, including
termination of a harmless local Python child and simulated Pulse stream-removal
acknowledgement. Python compilation passed. The inspect-only command correctly
reported `linux_pulseaudio_required` on Windows and opened no audio. These are
not Linux backend, real Bluetooth or Pi playback acceptance results.

The reference Deck now has `pulseaudio` and `pulseaudio-module-bluetooth` at
`17.0+dfsg1-2+rpt1`, with `libsbc1` at `2.1-1`. Installation added only the two
missing packages, with no upgrades or removals. The Bluetooth radio remains
blocked, the private server has no Bluetooth discovery module loaded, and the
configured USB audio hardware is absent. Loading the documented module,
selecting a phone bond and physical acceptance are still required. Package
installation does not establish actual A2DP reception.

PulseAudio 16.1 and 17.0 omit module IDs from their JSON module list. The receiver
uses the explicit IDs in `pactl list short modules` to verify ownership of the
processed output, and the JSON `monitor_source` field to reject monitor input.
Thirty focused checks pass on Windows and on the Pi using synthetic audio
boundaries; the corrected parser also reads the Pi's real PulseAudio 17 module
list successfully. These checks do not replace the phone/profile/playback tests.
