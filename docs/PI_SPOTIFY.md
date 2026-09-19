# Spotify through the Pi speaker

The Pi has its own Spotify Connect receiver, independent of the round speaker.
In **Music → Spotify**, **This display** controls the local Pi receiver; **Round
speaker** explicitly selects the existing round receiver. There is no automatic
switch to another room when an output is missing.

![Pi Spotify controls with synthetic music and an independent receiver name](images/pi-spotify.png)

## Install the receiver

Use a 64-bit Linux Pi OS and install `alsa-utils` for its `aplay` output. The
receiver is compiled on a Docker host so build tools and compiler caches do not
consume the Pi's SD card. From the repository on that host, run:

```bash
python tools/build_pi_receiver.py
```

Use `--docker-context YOUR_CONTEXT` for another Docker host. The helper sends
only the pinned build files and checksum-verified librespot source. It writes
`output/pi-receiver/echo-librespot`, `SHA256SUMS` and the upstream MIT license.
The target is ARM64 Linux; this executable is not for 32-bit Pi OS.

Copy those files and `deploy/pi` to the Pi. As the normal desktop user, install
the executable using the SHA-256 value from `SHA256SUMS`:

```bash
python3 deploy/pi/install_receiver.py --binary ./echo-librespot --sha256 YOUR_BUILT_BINARY_SHA256
python3 deploy/pi/setup.py --install
```

Pair the Pi first if this is a new display installation. The installer verifies
the checksum and architecture, preserves an existing executable as
`echo-librespot.previous`, and does not enable playback. Normal bundle rollback
still works without modifying the original SD backup or display pairing.

## Select the attached output

1. Attach the Pi's speaker or audio interface.
2. Open **Settings → Spotify on this Pi** on that Pi's display.
3. Choose its named ALSA output and a Spotify name such as **Kitchen Echo**.
4. Keep the initial output volume at **2%**, check **Enable this Spotify receiver**,
   and save. Changing its name or output restarts only that receiver.
5. Open Spotify on your phone, start a track, and choose the configured name in
   Spotify's device picker. Spotify Premium is required. Use the same LAN for
   initial discovery. The on-screen QR opens Spotify on the phone; it is not an
   account-linking code.

The output selector lists ALSA names without opening a device. A missing output
stops playback rather than selecting HDMI, headphones or another endpoint.
PulseAudio/PipeWire users may choose their system's shared output; direct hardware
outputs can be exclusive. Verify that voice replies and music can share the
selected physical device. Browser replies use Chromium's output, which must
point to that same speaker; choosing a Spotify output does not change Chromium.

The Spotify slider controls the incoming stream. **Output volume** is a separate
Pi attenuation control, limited to 30%. These controls do not change an external
amplifier's physical volume.

## Voice, calls and privacy

Opening the display's microphone first pauses Pi Spotify playback and closes its
output stream. Calls and announcement delivery use the same coordination.
Playback remains paused afterward; press Play or use Spotify to resume. If the
host cannot confirm the pause request, capture does not start. Tab focus leases
expire after 15 seconds, but expiring a lease never automatically resumes music.

Local music controls retain the display's pairing check and browser origin
protections. Spotify's own authenticated LAN receiver is a separate connection.
No microphone audio is sent to Spotify. Track metadata and cover art remain in
memory; bounded covers are fetched only from the current Spotify image URL.
The receiver disables its credential and audio caches and uses the user's
private runtime directory for temporary files. After a receiver restart, select
it from Spotify again; account credentials are not persisted by this adapter.

## What has been verified

The ARM64 executable builds from pinned source and starts on the Pi. Synthetic
checks cover stereo PCM attenuation, actual Linux pipe delivery and shutdown,
output selection without fallback, bounded controls, pause-before-microphone,
pairing revocation and UI destination separation. No audio device is opened by
those checks. Real Spotify sign-in/discovery, decoded music playback, audibility
and coexistence with the chosen physical output remain hardware acceptance.
