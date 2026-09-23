# Deck audio, camera and calling bring-up

Use this sequence when replacing the microphone, speaker or camera. A running
service or attached USB device does not establish clear sound or usable video.
Perform capture, playback and call tests with someone at the device.

The planned hardware is an **Arducam IMX519 16MP autofocus CSI camera with case**,
a **Waveshare USB TO AUDIO** interface, and **USB 2.0 mini microphones** as
alternative capture inputs. These are integration targets, not completed hardware
acceptance. Compare one microphone at a time; two USB microphones do not become
a beamforming array just by connecting both.

## Connect and identify

The Deck touchscreen uses HDMI for video and USB for both touch and power; it
has no separate power input in this build. Size the Pi's power supply and cable
for the Pi plus its USB peripherals, and check for undervoltage after connecting
the display and audio hardware. Stop playback and disconnect the audio board's
power before wiring a passive speaker.

The Waveshare **USB TO AUDIO** board supplies onboard microphones and amplified
speaker outputs over USB. It is not an analog headset-microphone adapter. Confirm
the delivered board's speaker load and connector pinout against its
[product information](https://www.waveshare.com/usb-to-audio.htm) and
[manual](https://www.waveshare.com/wiki/USB_TO_AUDIO).
The supplied [manufacturer PDF](https://m.media-amazon.com/images/I/A14RZIIF-aL.pdf)
specifies USB 5 V power, an SSS1629A5 codec, PH2.0 audio connectors and
**2.6 W per channel into 4 ohms, BTL**. It also illustrates an 8-ohm speaker.
Connect a passive speaker across the two terminals of **one** amplifier channel.
Do not join left/right outputs or ground either speaker terminal. Verify the
salvaged speaker's impedance before making an adapter. Start at 2% volume.

A USB UVC webcam normally uses Linux's `uvcvideo` driver and can work directly
with Chromium. Verify the actual model and detected capabilities. A CSI ribbon
camera uses the Pi camera stack; a working `rpicam` preview does not establish
browser/WebRTC compatibility. Connect CSI ribbons only with Pi power off.

Keep microphone openings clear and away from the speaker cone. A webcam's own
microphone must not silently replace the intended Echo input.

## IMX519 driver and browser gates

Use the Pi 4B's **CAMERA/CSI** connector, not its **DISPLAY/DSI** connector.
Confirm the supplied ribbon orientation against the board and camera markings
with power disconnected. This camera uses the ribbon, not a USB port.

Old installer reviews must be matched to the actual OS and kernel. Raspberry Pi's
[6.12 kernel sensor driver](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/drivers/media/i2c/imx519.c)
and [IMX519 overlay](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/arch/arm/boot/dts/overlays/imx519-overlay.dts)
already include the sensor and an AK7375 lens-controller binding. Upstream source
presence does not prove those components are installed in a particular image.

Before changing packages or boot settings, record:

```bash
cat /etc/os-release
uname -r
modinfo imx519
modinfo ak7375
ls /boot/firmware/overlays/imx519.dtbo
dpkg-query -W rpicam-apps python3-picamera2 libcamera-ipa
rpicam-hello --list-cameras
```

Preserve boot configuration before any required overlay change. Use the installed
kernel's overlay documentation; do not append duplicate camera settings or replace
the working kernel with an older vendor package. Prefer compatible distribution
packages: the [Picamera2 project](https://github.com/raspberrypi/picamera2) recommends
APT so Picamera2 and libcamera versions are matched.

Check sensor capture and lens control separately. The standard
[VC4 IMX519 tuning file](https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/vc4/data/imx519.json)
inspected during preparation has no `rpi.af` algorithm section. A detected sensor
or lens motor therefore does not by itself establish working autofocus. Inspect
the installed tuning and advertised `AfMode`/`LensPosition` controls, then test
near/far focus. Review any vendor additions against the actual OS before installation.

### Sensor detection checkpoint

On 2026-09-22, the attached IMX519 enumerated after backing up the boot
configuration, disabling camera auto-detection and selecting the installed
`dtoverlay=imx519` overlay, then rebooting. `rpicam-hello --list-cameras`
reported the 4656×3496 sensor and its available modes. The kiosk, USB audio
service and local wake listener returned, preserving their saved output levels.
That checkpoint confirmed detection only. On 2026-09-23, Picamera2 produced clear
640 × 360 frames and the AK7375 lens passed a contrast-based focus sweep.
The virtual webcam passed an FFmpeg reader lifecycle check. Chromium virtual
capture timed out, so Meet compatibility remains unresolved. See
[Deck camera](DECK_CAMERA.md) for the implemented preview and private-call path.

Finally verify browser capture. A CSI sensor's raw V4L2 node is not necessarily a
usable Chromium webcam. If the installed browser cannot consume the camera stack,
an explicit libcamera-to-virtual-webcam bridge is a candidate. The
[v4l2loopback project](https://github.com/umlaeute/v4l2loopback#options) documents
`exclusive_caps=1` for Chrome/WebRTC compatibility; the producer must be running
before that virtual device advertises capture capability. Such a bridge is not
installed or enabled merely by this guide. Its producer must stop on camera-off
and hang-up before it is integrated with Echo's privacy controls. Do not leave
an always-running capture service behind a visually disabled camera button.

## Inventory without capture or playback

Run on the Pi as its normal desktop user:

```bash
lsusb
arecord -l
aplay -l
v4l2-ctl --list-devices
v4l2-ctl --list-formats-ext --device /dev/video0
systemctl --user is-active echo-audio.service echo-display-bridge.service
systemctl is-active kiosk.service
vcgencmd get_throttled
```

Replace `/dev/video0` with the camera capture node from the inventory. Pi codec
and camera metadata nodes are not webcams. The distribution's `v4l-utils`
package supplies `v4l2-ctl` if needed. Listing formats does not start a stream.
Resolve USB disconnects or undervoltage before diagnosing choppy audio.

### USB audio checkpoint

On 2026-09-22, the separate USB microphone enumerated as `08bb:2902` with
mono 16-bit capture at 44.1/48 kHz. The Waveshare interface enumerated as
`0c76:1203`, with stereo capture/playback including 48 kHz. Check
`/proc/asound/card*/usbid` and `stream0` to match interfaces to their capabilities;
the friendly vendor label from `lsusb` alone can be misleading.

The prototype uses persistent ALSA names `EchoMic` and `EchoSpeaker`, matched to
those USB IDs by local udev rules, rather than detection-order names such as
`Device` and `Device_1`. These rules assume one connected device of each ID;
multiple identical adapters need serial-number or physical-port matching.
The separate microphone is the selected input; the Waveshare's onboard microphone
is not mixed into it. Both processed endpoints start successfully. A short 2%
test chime was heard after removing the interface's additional 20 dB playback
attenuation. A ten-second capture completed without errors or clipping, and
local transcription recognized the spoken counting sequence. Its low level led
to an approximately 18 dB microphone-gain adjustment, with hardware automatic
gain disabled and direct microphone playback muted. The local audio service
reapplies these mixer settings at startup; application output remains 2%.
Wake accuracy with the adjusted gain, echo reduction, duplex calling and
reconnect/reboot acceptance still require physical checks. The Pi continued
to report intermittent undervoltage during this setup.

## Route the new audio interface

Back up the private audio configuration. Follow [Pi echo cancellation](PI_ECHO_AUDIO.md)
to bind the actual named ALSA microphone/output to the dedicated audio service.
Check its required 48 kHz capture/playback support. Replacing USB hardware can
require regenerating static bindings; saved device names alone prove nothing.

```text
USB microphone -> echo_cancelled -> wake listener / Chromium microphone
Echo / Spotify / Chromium -> echo_processed -> USB amplifier -> speaker
```

Verify both processed endpoints exist on the private PulseAudio server. Select
them under **Settings → Talk to this Pi**, and select `echo_processed` for
Spotify and alarms. Restart the kiosk after changing audio selections so it
receives the same audio server. Direct hardware playback bypasses the reference
used by echo cancellation. Keep initial output at 2%.

## Physical acceptance

| Test | Passing result |
| --- | --- |
| Announced short microphone capture | Clear speech from the normal position, without clipping, dropouts or an unintended camera microphone. |
| Short speaker sample at 2% | Comfortable continuous output, without repeating static. |
| Wake and reply, then repeat with quiet music | Audible cue, understood speech, appropriate music ducking and recovery. |
| Explicitly enabled camera preview | Correct camera, orientation and framing; stable low-resolution video. |
| Deck ↔ permitted phone/laptop video call | Both directions work; mute, camera off and hang-up work; capture devices close afterward. |
| Intercom in both directions | Explicit answer, intelligible duplex audio, mute/decline/hang-up, and no wake transcription of the call. |
| Controlled USB reconnect and reboot | Intended devices and shared audio return without changing microphone or raising volume. |

Open video calls through **Planner → Room audio → Voice & video**. Echo already
requests 640×360 at 20 fps and starts playback at 2%. Turn the camera on explicitly.
Keep endpoints separated, or use headphones remotely, to avoid room feedback.

For intercom, enable room permissions and **Enable calls here** on both paired
endpoints. Deck-to-Mini also requires verified Mini firmware, connectivity and
matching host support. Follow [round intercom](ROUND_INTERCOM.md), preserving
the original flash backup before any required installation. A second paired
browser can test Deck intercom while Mini acceptance remains pending.

## Google Meet feasibility

Google lists Debian-based Linux and supported browsers in its
[Meet requirements](https://support.google.com/meet/answer/7317473?hl=en).
A Pi browser trial is reasonable, but this does not establish Raspberry Pi
ARM/Chromium certification or smooth video performance. Check the installed
browser, available RAM, camera capture and sustained CPU temperature first.

For a trial, pause Echo listening and playback, then open Meet in a separate
normal browser window using the intended audio interface. Sign in to Google
directly, join a meeting link and grant camera/microphone permission. Start at
360p with one remote participant and effects off. Leave the meeting and close
capture before restoring Echo listening.

Calendar OAuth does not sign Chromium into Meet. Echo's LiveKit codes and private
intercom do not join Meet meetings. Echo now includes an experimental Meet
launcher with temporary audio focus in **My day → Your camera**. A successful
Google sign-in and real media call remain unverified, including CSI virtual
camera compatibility. Meet uses Google's service rather than Echo's private
calling server.

See [Calling](CALLING.md) for video permissions and lifecycle limits, and
[Room audio](ROOM_AUDIO.md) for paired intercom setup.
