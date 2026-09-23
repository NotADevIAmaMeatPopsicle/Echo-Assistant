# Deck camera

**My day → Your camera** contains the Deck's own camera controls. Home Assistant
camera feeds remain separate. Camera use requires an online Household display;
opening the page alone does not capture an image.

## Preview and focus

Choose **Open preview**, then **Focus once** if needed. The IMX519 implementation
uses a contrast sweep of its AK7375 lens motor. This is one-shot focus, not
continuous subject tracking. Manual focus, Mirror and Rotate 180° are available.
Close camera, leave My day, or use the camera-off indicator to end the preview.

The Pi produces 640 × 360 JPEG frames in RAM. Closing capture removes them.
The browser holds the current preview only; Echo does not save recordings.
Capture leases expire if the controlling page disappears or loses access.

## Ask about an image

Open the preview, type a question, then choose **Send this frame**. The page shows
the configured image model and provider before sending one JPEG. Echo does not
add it to memory or invoke tools from the image response. Provider-side handling
follows the selected provider's policy. Choose an image-capable model in Echo
Settings; text-only deployments may reject the request. Keys stay on the host.

## Calls

**Open calls** leads to **Room audio → Voice & video**. Join a configured private
call and explicitly turn the camera on. The Deck turns its local preview into a
browser video track at up to 10 fps, without asking Chromium to open raw CSI
nodes. Other browsers use their normal camera permission dialog. Turning video
off or ending the call releases capture. A real two-device call is still needed
to assess image delay, speech quality and echo cancellation.

**Open Google Meet** accepts a meeting code or `https://meet.google.com/` link.
On the Pi it opens a separate window with the selected audio interface, quiet
output and temporary Echo audio focus. Close the window to return. Google
sign-in happens in Google's page; Calendar OAuth does not sign into Meet.

Meet's CSI-camera path is **experimental**. The optional virtual webcam passes
FFmpeg capture tests, but Chromium virtual-camera capture has timed out on the
development Pi. This is not verified Meet video support. A supported USB webcam
is a separate option. No live Meet call has been accepted yet.

## Optional motion wake

**Settings → Calls & camera → Camera motion wake** is off by default. Enabling it keeps the sensor
active and compares reduced frames locally. Motion can wake the screen; this is
not person recognition. No image is sent to an AI provider by motion detection.
Preview or calling suspends motion wake; re-enable the setting to resume it.
The camera-on indicator and **Turn camera off** remain available.

## Pi setup

First follow the sensor and power checks in [AV bring-up](AV_BRINGUP.md). Use
distribution packages matched to the installed kernel:

```bash
sudo apt install python3-picamera2 ffmpeg v4l-utils
```

Install the current Pi bundle using [Smart display setup](SMART_DISPLAY.md).
The worker uses system Python, so Picamera2 need not be installed in the voice
virtual environment. Preview and private Echo calls do not need a virtual webcam.

For the experimental Meet bridge only, install matching kernel headers and:

```bash
sudo apt install v4l2loopback-dkms
sudo python3 deploy/pi/setup_camera.py
```

The installer reserves `/dev/video42` as **Echo Camera**, checks conflicting
configuration and enables exclusive capabilities. Loading the module alone
does not turn on the sensor.

## Verification

The IMX519 has produced a clear 640 × 360 image and responded to a focus sweep.
On the Pi, Chromium received a live 640 × 360 canvas-backed LiveKit video track;
the local camera API also returned JPEG frames and confirmed capture off after
release. This checks local browser capture, not remote delivery or call quality.
The virtual producer starts with black frames, captures while an FFmpeg reader
is present, and releases capture when the reader closes. A synthetic image
received a valid response from the configured provider. Automated tests cover
access changes, exclusive leases, input bounds and image request isolation.
Sustained calls, Meet compatibility and motion-wake behaviour in a furnished
room remain physical acceptance items.
