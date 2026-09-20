# Managed private calling

**Deployed; physical call quality remains unverified.** The managed server uses
the existing private Docker host and Echo HTTPS gateway. It requires no new cloud
account. Two synthetic browser participants established nominated, selected TCP
connections through the deployed gateway with no microphone, camera or playback.
The owner and explicitly selected paired Deck can start calls. Fresh installations
remain disabled until configured and checked.

## Connection layout

| Connection | Route |
| --- | --- |
| Browser signalling | The existing Echo HTTPS origin, using `/rtc`, `/rtc/v1` and their `/validate` paths only |
| Browser media | TCP 7881 on the host's verified Tailscale IPv4 address |
| Provider administration | API container to `http://echo-calling:7880` on the private Compose network |
| Provider ports on Windows | Docker publishes 7880 and 7881 on `127.0.0.1` only |

The gateway checks the same source IP and stable Tailscale node ID used by the
existing UI allowlist before forwarding signalling or media. It does not grant
access to other members of the tailnet. The raw TCP listener has connection
limits, backpressure, time limits and repeated identity checks. Identity results
can remain cached for 15 seconds. The signalling route does not forward owner
cookies or expose LiveKit administration methods.

The server is LiveKit 1.13.7, pinned by digest in
[`deploy/host/calling.yaml`](../deploy/host/calling.yaml). This route uses
TCP only, with no UDP port, public STUN service or TURN server. Upstream labels
`force_tcp` a testing option. The actual browser-to-gateway TCP route has passed;
that does not establish physical media quality or future-version compatibility. Tailnet policy and Windows
firewall rules must also permit that specific TCP path; this overlay does not
modify either.

## Deployment settings

Set `calling_private_origin` in the ignored `local/deployment.json`, or provide
`ECHO_CALLING_PRIVATE_ORIGIN`. Its value is the canonical WSS form of the existing
Echo HTTPS origin, such as `wss://YOUR_HOST.YOUR_TAILNET.ts.net:18469`. This is a
deployment setting, separate from the calling credentials saved in the owner UI.
The two origins must match exactly. Only that match enables fixed internal
administration and tells the browser to omit public STUN discovery. An ordinary
external LiveKit provider retains its existing connection behavior.

The optional gateway block is absent by default. When configuring a verified
deployment, add `calling` to its private `tailnet.json` with `enabled: true`,
`media_bind_address` equal to the verified host Tailscale IPv4 address already in
`bind_addresses`, and `local_origins` containing only the loopback browser origins
actually in use. The Pi kiosk uses `http://127.0.0.1:8790`. The normal Echo HTTPS
origin is allowed automatically. Preserve the existing device allowlist and
roles. `{"enabled": false}` disables the calling routes and listener.

`tools/remote_device.py` includes the optional Compose overlay on normal API
start/stop when this binding is configured. On first setup, populate the provider
volume before starting its service; the API can be started with Compose
`--no-deps` while preparing that volume.

## Credentials and recovery

Save the exact WSS origin and strong provider key/secret through the owner calling
settings while calling remains disabled. Credentials stay in the existing
encrypted `CallStore`; they must not be placed in Compose, Git, command arguments
or logs. The key identifies this private LiveKit server, not a cloud account.

Inside the existing Linux API container, run the following as its normal service
user, substituting the verified host Tailscale IPv4 address:

```text
python tools/private_calling_config.py --node-ip YOUR_TAILSCALE_IPV4 --output /run/echo/calling-new.json
```

The helper accepts only a new file directly in the owned 0700 runtime directory,
creates it with mode 0600, and prints only a saved boolean. It refuses symlinks,
overwrites, an unmatched origin and missing saved credentials. Its JSON output is
also valid YAML for LiveKit. Transfer it privately to `livekit.yaml` in the
`echo_calling_config` Docker volume, owned by UID/GID 10000 and mode 0600, with a
0700 parent directory. The server mounts that volume read-only. Remove the exact
temporary runtime file once the private transfer is verified. Do not display its
contents or put a plaintext copy in a source checkout.

Echo's encrypted recovery archive already includes the calling credential store.
After restoring that store and its protection key, regenerate the provider file
with the reviewed destination origin and Tailscale address. The provider volume,
gateway certificate and device allowlist require explicit destination setup;
restoring an archive alone does not establish working calling. A fresh-machine
recovery rehearsal remains open.

## Acceptance boundary

`tools/check_calling_tcp.py` runs a disposable server with the pinned image and
bundled browser SDK. It requires a nominated, selected TCP candidate pair in a
connected peer connection. A WebSocket handshake or created room is insufficient.
It uses synthetic participants, forbids microphone/camera capture and playback,
and removes only its owned container, network and SSH forward. Its ordinary Docker
bridge is not an egress-isolated network.

The loopback/SSH rehearsal failed during ICE negotiation. The actual Tailscale
route exposed and resolved a gateway compatibility issue: the bundled client
uses `/rtc/v1` and its validation path. Both protocol versions now have exact
routes with the same access controls. The deployed Tailscale route subsequently
passed with two synthetic participants, verified remote TCP address and port,
and zero capture/playback calls. The generic loopback checker remains a diagnostic,
not the evidence for that deployed-route result.

The implementation passed 41 focused Linux API/configuration tests, including
real private-file ownership and symlink checks, plus 34 gateway tests. The Pi
received the updated client and calling permission, and its kiosk was refreshed.
Actual duplex sound, camera opt-in, hang-up, music focus and phone behavior still
need separate physical acceptance. See [Calling](CALLING.md).
