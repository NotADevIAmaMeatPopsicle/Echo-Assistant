# Contributing

Discuss substantial hardware/protocol changes in an issue first. Include the board
revision, host OS, software version and a minimal reproduction. Redact network
addresses, device IDs and account details. Never attach a full flash backup,
configuration directory, token, audio recording or conversation database.

Use Python 3.13 and the pinned requirements. Run:

```text
python -m unittest discover -s tests -v
python tools/release_guard.py
pio run -e round_voice
```

Unit tests use synthetic services and must not operate real appliances, invoke
paid models, flash boards or play audio. The [package checks](docs/PACKAGE_CHECKS.md)
include a silent browser suite and Linux pipe tests. Other `tools/check_*`
commands can be live hardware diagnostics; read their descriptions before use
and keep those out of CI. Record physical observations separately from successful
compilation or transport counters.

Keep configuration portable, source URLs/checksums pinned where used, and
third-party licenses/attribution intact. Contributions are provided under the
repository's GPL-3.0-or-later license unless a file states another applicable
third-party license. Use GitHub's private vulnerability reporting for sensitive
findings, not a public issue containing exploit credentials.
