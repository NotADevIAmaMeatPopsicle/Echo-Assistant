# Checking the complete package

Software checks use temporary stores, synthetic home devices and generated audio
samples. They do not establish microphone quality, speaker audibility, thermal
behavior or physical fit. Those remain in the [build queue](BUILD_QUEUE.md).

## Host and firmware

From the checkout with the pinned host requirements installed:

```text
python -m unittest discover -s tests -v
python tools/release_guard.py --worktree
python -m platformio run -e round_voice
python tools/firmware_bundle.py
```

The bundle command archives and verifies all four flash images without touching
a device. The board identity and original backup are still required for a later
flash. Platform-dependent tests report skips; they are not passing evidence for
an untested platform. CI includes separate Windows host, Linux Pi-client and
firmware jobs.

For a fresh Docker context, use `python tools/build_remote_host.py --stage-only`.
It selects tracked source, checks common private-artifact patterns, verifies the
native-source checksums, and preserves the previous context outside the image.
An explicit Docker build still needs network access for pinned dependencies.
Building an image does not provision a host or migrate private settings.

### Isolated installation and recovery rehearsal

After staging the source, build a separate test tag and select the Docker context
explicitly:

```text
docker --context YOUR_DOCKER_CONTEXT build -t echo-host:recovery-check deploy/host/context
python tools/check_host_recovery.py --context YOUR_DOCKER_CONTEXT --image echo-host:recovery-check
```

The check uses only that existing image, newly named and labeled disposable
volumes, and generated credentials. Containers have no network, published ports or
device mounts. It boots the actual API, creates a sample note, photo and display
pairing, checks owner/display permissions, restarts the container, and restores
the recovery archive into a second empty volume. It verifies the photo bytes,
room policy, pairing and calendar duplicate-protection record after restore.
It removes only its own labeled containers and volumes; production stays running.

On Windows the test archive uses the actual account-bound DPAPI protector. On
Linux it uses a temporary AES key for the test envelope. This proves the API data
path, not Windows Scheduled Task recovery, Hermes recovery, provider access or a
physical power cycle. `tests.test_recovery_archive` separately covers legacy
archives, corrupt blobs, unsafe archive members, linked targets, interrupted file
replacement and suppressing old announcement playback.

## Display flows

The browser checks require an existing Node runtime, Google Chrome and
Playwright. To install the test dependency locally, if needed:

```powershell
npm install --prefix local/ui-checks --ignore-scripts playwright@1.62.1
$env:NODE_PATH = (Resolve-Path local/ui-checks/node_modules).Path
python tools/check_display_suite.py
```

On Linux, set `NODE_PATH="$PWD/local/ui-checks/node_modules"` for the command.
Use `--node PATH_TO_NODE` when Node is outside PATH. The runner installs nothing.

Each check starts its own loopback demo on a free port and closes only that
process afterward. Browser checks verify the server identifies itself as a
synthetic preview before making requests. They do not accept a live Echo URL.
Results and screenshots stay under ignored `output/`.

The suite covers planning, lists, photos, connection loss, conversation,
touch typing and English swipe entry (`--check display_keyboard`),
shared text fields and modal keyboards (`--check display_form_keyboard`),
owner/guest display access (`--check display_profiles`),
Home tile choices and touch page navigation (`--check display_home`),
microphone permission cancellation, daily briefing, calendars, music, cameras,
announcements, intercom and the Pi's native voice/music/alert controls. It checks
the 1024 × 600 layout and phone widths. To investigate one failure without
repeating the rest, use `--check display_music`, for example.

The audio worklets and Linux child-process paths have separate silent checks:

```text
node tools/check_display_capture.cjs
node tools/check_intercom_worklet.cjs
python tools/check_pi_listener_pipeline.py
python tools/check_pi_music_pipeline.py
```

The last two run on Linux with synthetic child processes in place of ALSA. They
do not open a real input/output or download a wake model.

## Galleries and private data

Use `tools/preview_smart_display.py` for manual UI review. Its state is temporary.
For the round display, run `tools/preview_firmware.py` followed by
`tools/readme_gallery.py`; this renders the actual firmware scenes with sample
data. See [image provenance](images/README.md).

Documentation images must come from synthetic previews or reviewed, sanitized
prototype photographs. Keep live-home captures, host configuration, paired
credentials, audio, model weights, build contexts and backups outside Git.
No check or green build authorizes publication or changes repository visibility.
