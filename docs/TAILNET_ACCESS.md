# Private access from selected devices

The optional HTTPS gateway in `tools/tailnet_gateway.py` serves Echo and the
alternate Hermes WebUI to an explicit device allowlist. It verifies both the
connection's actual Tailscale IP and Tailscale's stable node identity. Another
member of the same tailnet or account is not automatically permitted. Forwarded
identity headers are discarded. Existing tailnet ACLs, tags and Serve rules are
unchanged; those rules must also permit the intended connections.

This helper currently targets the **Windows Docker host** used by the managed
deployment. It reads Echo's current-user DPAPI bootstrap to mint browser sessions.
Run it under the same Windows account that provisioned Echo. It is a trusted
administration gateway, not a limited guest-access mode: allowed devices can use
the full UIs. Keep a lock screen on those devices and revoke lost devices.

## Prepare the host

1. Complete [Docker deployment](DEPLOYMENT.md), including the alternate WebUI.
2. Install/sign in to Tailscale on the host and the devices you want to allow.
   Enable HTTPS certificates for your tailnet. Do not use Funnel.
3. Create an isolated Python environment on the host and install
   `config/tailnet-requirements.txt`. Use absolute interpreter/tool paths when
   configuring a background task.
4. Keep the gateway script, configuration, certificates, key and status file in
   the provisioning account's private `%LOCALAPPDATA%/Echo` directory, outside
   Git. Retain its restricted ACL from provisioning.
5. Use `tailscale status --json` to obtain the host's `Self.ID`, `Self.TailscaleIPs`
   and `Self.DNSName` (without its final dot). For each allowed peer, retain its
   `ID` and `TailscaleIPs`. Do not publish that inventory.

Create `tailnet.json` privately using this **example template**. All values below
are placeholders, sample addresses, or project defaults. Replace every uppercase
placeholder and both sample addresses with your own values. Absolute paths refer
to the Docker host, not the client. Begin with an empty allowlist to deny everyone.

```json
{
  "tailscale": "ABSOLUTE_TAILSCALE_EXECUTABLE",
  "docker": "ABSOLUTE_DOCKER_EXECUTABLE",
  "hostname": "YOUR_HOST.YOUR_TAILNET.ts.net",
  "host_id": "YOUR_HOST_STABLE_ID",
  "bind_addresses": ["100.64.0.1", "fd7a:115c:a1e0::1"],
  "allowed_devices": [],
  "cert": "ABSOLUTE_CERTIFICATE_PATH",
  "key": "ABSOLUTE_CERTIFICATE_KEY_PATH",
  "echo_bundle": "ABSOLUTE_API_BOOTSTRAP_DPAPI_PATH",
  "status": "ABSOLUTE_STATUS_JSON_PATH",
  "relay_port": 18647,
  "services": [
    {"kind": "echo", "port": 18469, "target": "http://127.0.0.1:18668"},
    {"kind": "hermes", "port": 18446, "target": "http://127.0.0.1:18647"}
  ]
}
```

Each allowed-device entry has `name`, `id` and `ips` fields. Supply the complete
intended set. `name` is informational; `id` and `ips` are checked. The host itself
needs an entry if you want it to open its own HTTPS address. The `echo_bundle`
field points to the existing `api-bootstrap.dpapi` created during provisioning.
The `127.0.0.1` targets mean this same host; they are loopback addresses, not
addresses of a particular user's machine. The port numbers are project defaults
used by the Compose deployment and gateway. The `cert`, `key`, and `echo_bundle`
values are placeholders for private file paths, not certificate or key contents.

Start with `python tools/tailnet_gateway.py --config YOUR_PRIVATE_CONFIG_PATH`.
It binds only the host's Tailscale addresses and a local Hermes relay, renews its
certificate, and denies access if identity verification fails. It will refuse to
start if the configured host identity or addresses no longer match Tailscale.

Open `https://YOUR_HOST.YOUR_TAILNET.ts.net:18469/` for Echo or port `18446` for
Hermes. Check one permitted device and one omitted device; the latter should
receive HTTP 403. No provider call or appliance actuation is required for this.

## Keep access current

To run at login, register a current-user Windows Scheduled Task named
`Echo Private Tailnet UIs`. Its action should invoke the isolated interpreter
with the absolute script path and `--config` path, with the private directory as
its working directory. Launch it hidden and without elevated privileges. On
Windows Docker Desktop this depends on that account's logged-in session.

After that task is configured, the client helper
`python tools/set_tailnet_devices.py --allow YOUR_LAPTOP --allow YOUR_PHONE`
replaces the **entire** allowlist with exact names from the host's Tailscale
inventory and restarts only that gateway task. It uses the SSH target configured
in `local/deployment.json`. It does not grant access to the whole account.

Node reenrollment or address changes require a fresh allowlist. Identity results
are cached for up to 15 seconds. Restart the gateway to apply an edited list.
Keep certificate keys, bootstrap bundles and status/inventory files out of Git.
