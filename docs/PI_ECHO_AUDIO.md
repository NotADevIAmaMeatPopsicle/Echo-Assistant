# Speaker echo cancellation on the Pi

Echo can use PulseAudio's WebRTC processing to reduce its own speaker audio in
the microphone signal. This gives the local wake listener a cleaner input during
music and enables the option to interrupt a spoken reply by voice. It does not
guarantee wake recognition across a room or remove other people's speech.

This optional setup is for a **dedicated Pi account using direct ALSA audio**.
If that account already uses an active PipeWire or PulseAudio desktop, keep its
audio setup and configure an equivalent processed source there. Do not mask a
desktop audio service that other applications depend on.

## How the audio connects

```text
Spotify, replies, chimes, Chromium
               |
        echo_processed ---- playback reference ----+
               |                                  |
        selected speaker                  WebRTC echo cancellation
                                                  |
        selected microphone ----------------------+
                                                  |
                                           echo_cancelled
                                                  |
                                           wake / capture
```

Both device selections matter: sound sent directly to a hardware output or to
another speaker supplies no reference to this processor. Use `echo_processed`
for Pi voice, Spotify and alerts. The dedicated kiosk also uses this audio server
when Pi voice selects **both** `echo_cancelled` and `echo_processed` at startup.
Other browsers and applications retain their own device settings.

## Install

The microphone must support mono 48 kHz and the playback device stereo 48 kHz,
either natively or through ALSA's `plughw` conversion. A full-duplex USB interface
can supply both. Begin with the [normal Pi voice setup](PI_VOICE.md).

1. Record the current voice, Spotify and alert device selections. Keep listening
   muted, stop playback and close the kiosk before changing the audio service.
   Back up `~/.asoundrc` and `~/.config/echo-display` privately; the latter includes
   pairing credentials. Do not add these files to Git.
2. Install the distribution packages. Run only this package command with `sudo`:

   ```bash
   sudo apt-get install --no-remove --no-install-recommends pulseaudio pulseaudio-utils libasound2-plugins
   ```

3. As the normal Pi user, check the existing services and physical card names:

   ```bash
   systemctl --user is-active pulseaudio.service pulseaudio.socket pipewire.service pipewire-pulse.service
   systemctl --user is-enabled pulseaudio.service pulseaudio.socket
   arecord -l
   aplay -l
   ```

   Inactive or missing desktop audio units are expected for this dedicated ALSA
   setup. An active desktop audio service needs its own integration instead.
   Record any pre-existing masks before continuing; rollback must preserve them.
4. Stop Echo's device users, prevent a competing default PulseAudio instance,
   and generate configuration. Replace the example card names with those from
   the inventory. Use the same name for input and output if they share a card.

   ```bash
   systemctl --user stop echo-display-bridge.service
   systemctl --user mask pulseaudio.service pulseaudio.socket
   python3 deploy/pi/setup_echo_audio.py --configure --input plughw:CARD=USB,DEV=0 --output plughw:CARD=Speaker,DEV=0
   systemctl --user daemon-reload
   systemctl --user enable --now echo-audio.service
   ```

   The helper preserves unrelated ALSA configuration and makes first-write
   `.before-echo-aec` backups of existing files. It never changes the system
   default, starts a recorder or adjusts mixer gain. The service starts only
   when explicitly enabled above.
5. Verify the service without playing sound:

   ```bash
   systemctl --user status echo-audio.service --no-pager
   pactl --server="unix:/run/user/$(id -u)/echo-audio/native" list short sources
   pactl --server="unix:/run/user/$(id -u)/echo-audio/native" list short sinks
   python3 deploy/pi/setup.py --install
   ```

   The lists must contain `echo_cancelled` and `echo_processed`. If startup fails,
   inspect `journalctl --user -u echo-audio.service -n 40 --no-pager`; check the
   selected hardware and whether another program owns it. Echo does not fall
   back to another audio card.
6. Reopen the kiosk. In **Settings → Talk to this Pi**, select microphone
   `echo_cancelled` and speaker `echo_processed`. Start at **2%** output. Enable
   **Interrupt spoken replies by voice** only with the processed input selected.
   Select **Lower music by 80%** for the requested music behavior. Under **Spotify
   on this Pi** and **Alarms on this Pi**, select `echo_processed` as well.
7. Save, then restart the kiosk using its existing launcher so Chromium picks up
   the shared server. Unmute when ready. Say a wake phrase, wait for the cue,
   and speak. Repeat with quiet music and then during an Echo reply. Check both
   recognition and whether the music returns to its prior level.

The service and device selections persist across login/restart. A USB device
name change requires reconfiguration; restarting the service alone cannot choose
a different device. The helper's `--check` reports installed programs and whether
configuration exists, not whether audio is working.

The voice status also checks that selected private `echo_cancelled` and
`echo_processed` endpoints exist on the dedicated audio server. ALSA names can stay
listed after hardware disappears, even when PulseAudio has no usable source or
sink. This read-only check is cached for five seconds and never opens a recorder,
plays audio, starts a service or selects another device. A missing processed route
reports that specific condition. Reconnect the intended hardware, verify its card
names, and then explicitly restart `echo-audio.service` if its static modules need
to be recreated; the listener retries without a bridge restart. Other ALSA and
independently managed processed paths retain their existing selections. Missing
selected devices, wake-model loading failures and a disconnected speech host have
separate status messages; these diagnostics do not establish acoustic performance.

## Privacy and volume

The server uses a private, user-owned Unix socket. It loads no network listener
or automatic device-discovery module. WebRTC processes live buffers locally and
its audio-dump option is disabled. Normal command uploads follow the existing
[Pi voice privacy rules](PI_VOICE.md#privacy-and-recovery).

Automatic analog and digital gain are disabled. Noise suppression and the
high-pass filter are enabled; physical mixer gain stays as it was. Echo's output
level still applies separately. Software mute closes Echo's listener; it cannot
disconnect the microphone or mute other local programs using the audio server.

## Roll back

First mute Echo and stop playback. With the bridge still running, restore the
previous device selections in Pi voice, Spotify and alerts, and turn off spoken
reply interruption unless the previous input also cancels echo. Close the kiosk.
Then, as the normal Pi user:

```bash
systemctl --user stop echo-display-bridge.service
systemctl --user disable --now echo-audio.service
python3 deploy/pi/setup_echo_audio.py --remove
systemctl --user daemon-reload
```

The removal helper deletes its marked configuration and ALSA block; unrelated
settings remain. **Unmask only the default PulseAudio units you masked during
this installation**, preserving any original masks. For example, if both were
new masks:

```bash
systemctl --user unmask pulseaudio.service pulseaudio.socket
```

Start the bridge again with `systemctl --user start echo-display-bridge.service`
and reopen the kiosk. Keep the packages and private backups until the previous
audio route works. Removing Echo's configuration does not uninstall packages or
restore application device selections automatically.

## Verification boundary

The current Pi deployment loads the distribution's WebRTC module, delivers
processed frames to the native recorder, and points Chromium and Spotify at the
same output. A separate null-source/null-output check verified module startup
without opening audio hardware. Configuration tests cover preservation,
idempotence, rollback after write failure, and explicit kiosk routing.
The native listener also recovered fresh processed frames after restarting the
audio service, without restarting the bridge or playing test sound.

These checks establish the software route. Actual echo reduction, wake accuracy,
reply interruption, audibility and recovery after power cycling still require
the final microphone/speaker placement and physical acceptance.

Implementation reference: [PulseAudio module-echo-cancel documentation](https://www.freedesktop.org/wiki/Software/PulseAudio/Documentation/User/Modules/#module-echo-cancel).
