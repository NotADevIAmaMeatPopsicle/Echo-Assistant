# Security policy

Echo Assistant is alpha software intended for a trusted home LAN. Use explicit
device permissions, protect host credentials and do not expose management/device
ports directly to the internet. Software microphone mute is not a hardware switch.

Report vulnerabilities using this repository's **Security → Report a vulnerability**
feature. Include affected versions, reproduction steps and expected/actual behavior,
with synthetic credentials and devices. Do not post real secrets or private home
inventory in a public issue. No response-time guarantee is currently offered.

Sensitive stores, recordings, backups, device IDs, host-specific deployment files
and session artifacts must stay out of Git and release assets. Run the publication
guard and secret scanner on the exact proposed commit and assets before release.
Only the current alpha development line receives fixes; there is no supported
stable release yet.
