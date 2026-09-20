# Docker host deployment

Two dedicated containers run the application: `echo-api` supplies speech, UI,
device transport and integrations; `echo-agent` runs Hermes. The board talks to
the host directly. Browser tunnels are optional client access, not another copy
of the services.

The images are Linux/x86-64. **The managed remote provisioning scripts currently
target Windows with Docker Desktop and OpenSSH**, using that account's DPAPI and
Scheduled Tasks for recovery. A native-Linux provisioning path is not yet packaged.
Do not treat the Compose files as a fully configured one-command installation.

## Configure a host

Configure an SSH alias and a Docker context for your own host. Copy
`config/deployment.example.json` to ignored `local/deployment.json`, or set:

| Variable | Meaning |
| --- | --- |
| `ECHO_SSH_TARGET` | SSH alias or `user@host`; default alias `echo-host` |
| `ECHO_DOCKER_CONTEXT` | Your Docker context; default name `echo-host` |
| `ECHO_DEVICE_HOST` | Server's actual private LAN IPv4 address |
| `ECHO_BIND_ADDRESS` | Same LAN address for Compose device/Spotify listeners |
| `ECHO_DEVICE_MAC` | Your verified board identity for USB operations |
| `ECHO_LAN_SUBNET` | Explicit LAN CIDR when configuring discovery firewall rules |

Do not copy example addresses unchanged. Container paths such as `/opt/echo` are
part of the image layout; host filesystem paths are resolved on the appropriate
machine. The helpers do not alter your current global Docker context.

## Provision and migrate

First get the local host working, pair Wi-Fi, and configure your selected model
and optional HA settings. Confirm your SSH/Docker context reaches the intended
server before proceeding. The following tools perform real installation/migration;
read their help and retain a private recovery archive.

1. `tools/remote_agent.py start` builds/starts the isolated agent and provisions
   the selected settings through the private host helper.
2. `tools/build_remote_host.py` prepares an allowlisted build context and builds
   the API image. Native sources are checksum-pinned; downloads are explicit.
3. `tools/import_remote_models.py` imports existing local speech assets into the
   dedicated `echo_models` volume; it does not supply model weights in Git.
4. `tools/start_remote_api.py` provisions the isolated validation API and tunnel.
5. `tools/migrate_remote.py` performs a preflight only; `--execute` performs the
   board/host transfer. `--resume` is restricted to its documented rollback state.

The round-device Compose override requires `ECHO_DEVICE_MAC` and passes it into
the container for pairing validation. Set it to the identity verified from your
board before starting or recovering that deployment. The value is not included
in the image. The managed migration path still starts from a working round
installation; a new Pi-only host can use the local `-DisplayOnly` startup path.

`tools/build_remote_host.py --stage-only` prepares the Docker context without
building an image. Backend and web files must be reviewed and tracked in Git;
ignored local files are excluded. Each context is assembled afresh, with file
hashes in `context-manifest.json`. A previous generated context is preserved in
ignored `local/build-context-backups`, so removed source cannot silently remain
in a later image. Cached native sources are checksum-verified; missing ones are
downloaded only when this explicit build command is run.

Use the repository Python for these scripts. Startup thereafter uses
`tools/remote_device.py start`, and the desktop launcher targets the selected host.
Recovery archives use `tools/backup_remote.py`. A fresh API bootstrap, container
restart and encrypted-archive restore into a new volume have been exercised with
synthetic data. The full Windows recovery-task and Hermes disaster restore remain
acceptance items; the isolated API check does not prove those paths.

### Back up and restore saved data

Run from the configured checkout on the Windows account used to manage the host:

```text
python tools/backup_remote.py create
python tools/backup_remote.py inspect PATH_TO_ARCHIVE.echo-backup
python tools/backup_remote.py restore PATH_TO_ARCHIVE.echo-backup
```

Creation reads a stable snapshot without stopping Echo. The archive includes saved
settings, explicit memory, lists, schedules, routines, pairing, source permissions,
media presets, room-audio settings, doorbell state, calendar dispatch receipts and
the shared photo album. It excludes microphone recordings, conversations, browser
sessions, research results and model weights. Pi-local audio/screen settings and
browser Home tiles are on the Pi and require its own backup.

Version 2 archives contain a Windows-DPAPI-protected manifest and the album's
already encrypted photo blobs. The manifest protects their hashes and the storage
key. Photo ciphertext is copied one image at a time; plaintext images never enter
the archive. Inspect checks every member's size and hash before reporting success.
These archives require the Windows account that created them; retain access to
that profile when planning recovery onto another computer.

**Restore replaces the saved snapshot.** It first creates and verifies a recovery
point for the current installation, then stops the API and Hermes, stages all
replacement data, and restores the protected bootstrap before restarting them.
Ordinary file-write failures roll back the changed files; interrupted host power
still requires recovery from the retained archive. Queued announcements are
cancelled and previously claimed deliveries are marked uncertain, so restoring an
old queue cannot replay them. Restoring a snapshot does
not undo events or actions already sent to an external service.

Version 1 archives remain readable. They lack shared photos and the newer room
and calendar-receipt stores, so those are empty after a version 1 restore. The
automatically created version 2 pre-restore archive preserves the current data.
Use a recent archive when recovering calendar dispatch records.

## Browser access and storage

- `tools/open_ui.py` opens an authenticated Echo UI tunnel at `http://localhost:18669/`.
- `tools/open_hermes_ui.py` opens the alternate Hermes WebUI at `http://127.0.0.1:18646/`.
- `tools/open_hermes_dashboard.py` opens the native dashboard at `http://127.0.0.1:18645/`.
- Containers expose management endpoints on host loopback. The desktop helpers
  forward them through your authenticated SSH/Docker connection.
- The board listener is 8769 and Spotify's receiver is 18899 on the explicitly
  configured LAN address. Neither endpoint should be exposed publicly.

The agent uses a 512 MiB volatile home for conversations/logs and separate
disk-backed volumes for Python packages and uv cache. Its memory ceiling is
2.5 GiB; the API ceiling is 3 GiB. These are limits, not memory reservations.
Provision sufficient physical RAM for these plus other host applications.
Native dashboard configuration can be overwritten by Echo's saved configuration
on recovery. Use Echo Settings for durable model/personality changes.

The alternate WebUI comes from a checksum-pinned upstream source archive during
the agent image build. Rebuild the agent image to add it to an older deployment.
Both UIs use the same running Hermes gateway; neither starts another assistant
on the client laptop. UI session state remains in the container's volatile home.

For HTTPS access from selected phones/computers, see
[Tailscale access](TAILNET_ACCESS.md). Do not expose either unauthenticated
container-loopback UI directly to a LAN or the Internet.

## Optional Whisper on the Linux host

The API image includes the CPU-only faster-whisper runtime pinned in
`config/stt-linux.lock.txt`. Prepare the model using the explicit procedure in
[local setup](SETUP.md), then run the model importer again. It adds
`faster-whisper-base.en` when that local directory exists, copies only missing
model directories, and preserves an existing volume if hashes differ.

Select Whisper in Echo Settings after importing. Availability requires the
worker interpreter and all four model files: `model.bin`, `config.json`,
`tokenizer.json`, and `vocabulary.txt`. `ECHO_STT_PYTHON` selects an absolute
interpreter path; the container sets it automatically. The worker blocks network
access, uses two CPU threads, and receives audio in memory. Vosk still handles
wake detection and end-of-utterance detection. No model weights are in Git.

`tools/check_remote_stt.py` is an explicit diagnostic that starts a disposable,
network-disabled container to transcribe synthetic speech and silence. It does
not use the microphone, play audio, or contact Home Assistant.
