# Replacement Windows host

`tools/provision_host.py` packages **ECHO-10's software path**. A fresh-machine
rehearsal remains **ECHO-20, unverified**. These commands have synthetic tests;
they have not installed prerequisites or recovered the actual installation onto
a replacement machine.

The replacement path targets a Windows management account, Docker Desktop's
WSL 2 Linux/x86-64 engine, authenticated Windows OpenSSH, and the existing Echo
Compose/recovery helpers. It restores **loopback validation services**, with
device voice and home actions disabled by the existing validation mode. Moving
the Pi/round endpoint, enabling device listeners/discovery, LAN firewall changes,
provider acceptance and acoustic checks are separate operator steps. This is not
a native-Linux installer or a new deployment system.

Every action defaults to inspection. `--execute` is required for installers,
manifest output, model copies/import, and saved-data restoration. `plan` never
accepts `--execute`. Commands do not switch the global Docker context, restart
Windows, install SSH keys, or configure network access automatically.

## 1. Retain recovery artifacts

On the original installation, create a portable archive using
[the existing backup procedure](DEPLOYMENT.md#portable-backups). Keep its private
recovery passphrase separately. Model weights are excluded from this archive.

Create a manifest of the reviewed speech models and preserve the actual model
directories on separate recovery media. Run from the repository with its Python:

```powershell
python tools/provision_host.py models-manifest --source local/models --manifest backups/models-manifest.json
python tools/provision_host.py models-manifest --source local/models --manifest backups/models-manifest.json --execute
```

The command prints the manifest's SHA-256. Retain that digest in an independently
trusted location. Recovery requires it via `--manifest-sha256`; accepting a hash
from the same untrusted media as the manifest would not authenticate that media.
The manifest contains only reviewed model directory names, relative file names,
sizes and SHA-256 hashes. It contains no absolute paths, account/host identifiers,
passphrases or model bytes. Existing manifest files are never overwritten.

Required models match the existing importer: Pocket TTS, Kokoro and Vosk small
English. The CLI checks the TTS catalog's required weights, voices/configuration
and attribution files, and core Vosk files. A manifest containing faster-whisper
must include its four runtime files. The copied bytes must match the trusted
manifest; this does not prove that a model is correct for a particular voice or
that speech has been heard on physical hardware.

Retain reviewed Linux amd64 API and Hermes images, or the source checkout and
network access needed to rebuild them. Private settings and recovery archives
must never enter Docker build contexts or Git.

## 2. Install explicit prerequisites

Start on a currently supported, updated Windows release with hardware
virtualization enabled and a 64-bit Python 3.12–3.14 interpreter. Python 3.13 is
the recommended management interpreter. If no Python is available, install it
with the official installer or `winget install --id Python.Python.3.13 --exact`,
then open a new terminal. Clone or securely copy this checkout.

```powershell
python tools/provision_host.py
python tools/provision_host.py bootstrap --component docker
python tools/provision_host.py bootstrap --component docker --execute
```

Bootstrap always runs on **the machine running this command**, even when a
remote SSH/Docker target is configured. Run it locally on the intended replacement
machine. Select only one prerequisite per invocation:

| Component | Explicit operation |
| --- | --- |
| `git` | WinGet `Git.Git` installation |
| `python` | WinGet `Python.Python.3.13` installation |
| `docker` | WinGet `Docker.DockerDesktop` installation |
| `wsl` | WSL install without a distribution or immediate launch |
| `openssh-client`, `openssh-server` | Corresponding Windows optional capability |
| `recovery-env` | New virtual environment with repository-pinned cryptography, Pydantic and HTTPX |

WinGet/Windows feature installation may require an elevated operator terminal,
Internet access, vendor terms and a reboot. No elevation workaround or automatic
reboot is performed. An installer exit requiring reboot stops the action and
reports `ready: false`; otherwise rerun preflight to establish readiness. Already
installed packages remain under their installer/version manager's normal rules.

Create a separate environment without downloading audio models:

```powershell
python tools/provision_host.py bootstrap --component recovery-env --environment local/recovery-env --execute
./local/recovery-env/Scripts/Activate.ps1
```

An existing environment is refused. A failed partial environment is retained for
inspection; choose a new empty destination after correcting the reported issue.
No dependency install occurs in the interpreter that launched the command.

Start Docker Desktop, finish its first-run setup and select the WSL 2 Linux
engine. Configure authenticated Windows OpenSSH for the intended Windows account,
including the SSH service, trusted host key, firewall scope and authorized key.
The capability installer alone does not configure those. See
[Microsoft's OpenSSH setup](https://learn.microsoft.com/windows-server/administration/openssh/openssh_install_firstuse).
An SSH alias and Docker context must both reach the **same Docker daemon** that
the host recovery account uses by default. Preflight compares the daemon IDs
without printing them and refuses a mismatch. It never changes that account's
global context. Windows DPAPI and Scheduled Tasks use this selected account.

## 3. Select paths and inspect

Pass options directly, or store the following keys in ignored
`local/provision.json`: `ssh_target`, `docker_context`, `host_disk_path`,
`api_image`, `agent_image`, `source`, `destination`, `manifest`,
`manifest_sha256`, `archive`, `environment`, and `disk_reserve_gib`.
Credential fields are rejected. Relative artifact/environment paths in the file
resolve against the configuration file's directory; CLI paths resolve against
the current directory. `host_disk_path` is an absolute path **on the Windows
Docker host**, on the drive actually holding Docker Desktop's backing disk.
Do not point it at an unrelated drive with more free space.

```powershell
python tools/provision_host.py plan --docker-context RECOVERY_CONTEXT --ssh-target RECOVERY_SSH_ALIAS --host-disk-path D:/
python tools/provision_host.py plan --config local/provision.json
```

The report checks the Python/tool versions and recovery libraries, Windows build,
OpenSSH/WSL/virtualization state, pending Windows restart, Docker client/server,
Compose, daemon identity, RAM, free host disk, and both existing image artifacts.
The operational baseline is Docker 24+, Compose 2.20+, Windows build 19045+,
8 GiB physical RAM and 6 GiB assigned to Docker. Use a Windows version currently
supported by Microsoft and Docker, even if it exceeds these numeric minima.
Plan reserves at least 30 GiB free by default, or model bytes plus 10 GiB,
whichever is larger. This is a conservative capacity gate, not a measured build
peak; large image builds/caches and a full backing VHD may need more space.

### If Docker's system drive fills up

Free space on another drive does not help until Docker's data disk is moved there.
Docker Desktop supports relocating existing WSL data through **Settings → Resources
→ Advanced → Disk image location**. This is supported by Docker Desktop 4.55;
the [WSL guide](https://docs.docker.com/desktop/features/wsl/) describes the setting.

1. Record the current data-disk location. Stop the running containers cleanly and
   quit Docker Desktop completely before copying its actual `docker_data.vhdx`.
   Its directory varies between installations; use the existing file, not a
   guessed path. Keep a separate backup on a drive with sufficient capacity and
   verify its size and SHA-256 against the stopped original.
2. Start Docker Desktop, choose a new empty directory on the larger drive using
   **Disk image location**, then apply the change. Let Docker finish the move and
   restart. The destination for live data must be separate from the backup.
3. Confirm the new location, retained images and volumes, and existing Echo and
   Hermes data. Check health, pairing and settings before resuming builds. Keep
   the backup until these checks pass and update `host_disk_path` to the drive
   that now holds Docker's data.

Docker's [backup guide](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
requires Docker Desktop to be fully stopped for a VM-disk backup. The installer
flag `--wsl-default-data-root` specifies a default for installation; it is not a
documented migration command for an existing disk. Use Docker's relocation
setting rather than manually editing its settings file or unregistering its WSL
storage. Moving this disk interrupts every container on that Docker host, so
coordinate the maintenance window with any other services using it.

Missing models/manifests/images and unverified archives remain visible. Without
host options, the default plan still inventories available management tools and
reports missing configuration. Exit status 2 means blocked, incomplete or failed;
0 means the requested plan/action completed. `ready_to_validate_restore` does not
mean restored or ready for production: target occupancy, remote model hashes and
protected archive integrity are checked separately.

Load retained reviewed images explicitly with `docker --context RECOVERY_CONTEXT
load --input PATH_TO_REVIEWED_IMAGES.tar`. To rebuild instead, select
`ECHO_DOCKER_CONTEXT` for the terminal and use the existing paths:

```powershell
python tools/build_remote_host.py
python -c "from tools.remote_agent import compose; compose('build', 'agent')"
```

The latter builds the agent using its existing allowlisted build preparation;
it does not provision local saved settings or start services. Builds are explicit
network operations and require reviewed/tracked source. Also make the pinned
helper image in `tools/import_remote_models.py` available through a deliberate
Docker pull/load. The new wrapper refuses to import when that image is missing;
it does not silently pull models or images.

## 4. Restore and import models

Use a destination on NTFS, separate from the retained source. Substitute the
independently retained 64-character digest. These examples assume model media is
under `local/recovery-media/models` and the manifest outside that tree:

```powershell
python tools/provision_host.py models-restore --source local/recovery-media/models --destination local/models --manifest local/recovery-media/models-manifest.json --manifest-sha256 TRUSTED_SHA256
python tools/provision_host.py models-restore --source local/recovery-media/models --destination local/models --manifest local/recovery-media/models-manifest.json --manifest-sha256 TRUSTED_SHA256 --execute
python tools/provision_host.py models-import --source local/models --manifest local/recovery-media/models-manifest.json --manifest-sha256 TRUSTED_SHA256 --docker-context RECOVERY_CONTEXT --execute
```

Restore verifies all source bytes, paths, destination conflicts and disk space
before copying. It refuses traversal, absolute/Windows-special paths, duplicate
or case-colliding names, symlinks and junctions, and mismatched/extra destination
files. It atomically publishes verified missing files without overwriting an
existing name. An interrupted copy may leave verified files that the next run
reuses; conflicting data is preserved. Keep source/destination trees unchanged
while running. Filesystems without hard-link support are not supported as restore
destinations and fail without overwriting existing files.

Import delegates to `tools/import_remote_models.py --source ... --context ...`.
The dedicated `echo_models` volume must be Echo-owned; differing, extra or
partially populated model directories are refused. Default import planning only
verifies local files and helper-image presence; the report explicitly says the
remote volume has not been verified. No production volume is erased or repaired
automatically.

## 5. Restore saved data into empty validation services

Set `source` to the restored local model tree, select the archive, manifest,
trusted digest, images and target in your private provisioning configuration.

```powershell
python tools/provision_host.py restore --config local/provision.json
python tools/provision_host.py restore --config local/provision.json --execute
```

Plan identifies the archive envelope without unlocking it. Execution uses the
existing private-terminal recovery-passphrase prompt and protected archive
validation. Never put the passphrase in argv, environment variables or the config.
A Windows-protected archive still requires the original Windows account's keys;
use a portable archive for a replacement account.

Fresh restore refuses existing `echo-api`/`echo-agent`, data/package/cache volumes,
the Echo Compose network, or the host account's Echo directory/recovery/discovery
tasks and occupied management listeners. The already verified model volume is the one expected existing resource.
It pins selected local image IDs, creates services from the existing two Compose
files without builds/pulls, verifies attempt ownership, streams encrypted data
through the existing restore helper, installs the existing current-user recovery
task, and restores bootstrap credentials through DPAPI. The saved home-access
policy remains authoritative; queued announcements receive the existing restore
cancellation rules. An archived round identity is passed without its pairing key
to let bootstrap retain pairing, but no device voice listener is enabled.

Only both services reporting healthy produces `services_ready: true`. Failure
attempts to stop only containers owned by this restore attempt, retains encrypted
data/bootstrap and partial resources, and returns an error. Inspect their state
before manual repair. A second fresh restore refuses these resources; it never
deletes them to retry. The original archive is always preserved. For an existing
deployment, use the separately documented `backup_remote.py restore` workflow.

Run ECHO-20 on a disposable Windows machine/VM before treating this as established
fresh-machine recovery. Verify scoped service health and saved data there, then
separately approve endpoint/network migration and physical checks. Nothing in
this software task confirms external providers, device audio, or home actions.
