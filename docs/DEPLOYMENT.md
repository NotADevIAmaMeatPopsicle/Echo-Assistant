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

Use the repository Python for these scripts. Startup thereafter uses
`tools/remote_device.py start`, and the desktop launcher targets the selected host.
Recovery archives use `tools/backup_remote.py`; they are encrypted to the local
Windows account. Archive creation has been exercised; a complete live disaster
restore remains an acceptance item.

## Browser access and storage

- `tools/open_ui.py` opens an authenticated Echo UI tunnel at `http://localhost:18669/`.
- `tools/open_hermes_ui.py` opens the native dashboard at `http://127.0.0.1:18645/`.
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
