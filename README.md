# Kinatio

Kinatio is a Linux terminal observability console that combines an interactive Textual interface with automation-friendly CLI reporting. It brings host health, services, logs, network posture, storage, packages, sessions, audit posture, and backend status into one operator-focused surface.

## Release status

- current version: `1.0.0`
- supported platform: Linux
- required Python: `3.12+`
- public surface: observe-only TUI and CLI

## Interfaces

- `kinatio` starts the Textual TUI
- `kinatio tui` explicitly starts the TUI
- `kinatio scan ...` is the canonical non-interactive reporting interface
- `kinatio status` reports runtime, backend, and collector health

## Coverage

Kinatio currently covers:

- system identity, kernel, uptime, load, and runtime context
- hardware, performance, storage, sessions, power, packages, and containers
- interfaces, routes, DNS, listening ports, active connections, and firewall status
- service inventory across supported service managers
- log history and live follow across supported log backends
- security posture and audit summaries with explicit privilege handling

## Install

Recommended cross-distro bootstrap:

```bash
./install.sh
```

For contributor workflows:

```bash
./install.sh --dev
```

Manual fallback when `python3` is already `3.12+`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Quick use

Start the TUI:

```bash
kinatio
```

Discover the CLI scan surface:

```bash
kinatio sections
```

Inspect runtime and collector health:

```bash
kinatio status --json
```

Run a report:

```bash
kinatio scan system network storage
kinatio scan firewall --json
```

Unlock a privileged scan when needed:

```bash
kinatio scan logs --unlock
kinatio scan logs --follow --unlock
```

`--follow` is supported for logs only.

## Support model

- Linux only
- strongest release-host smoke path today is still hosts with `systemd` and `journalctl`
- deterministic test coverage exercises service-manager detection and inventory on `systemd`, OpenRC, runit, and SysV-style hosts
- deterministic test coverage exercises firewall detection and read-only status on `ufw`, `firewalld`, and `nftables`
- deterministic test coverage exercises package inventory and update parsing on `dpkg`, `rpm`, `pacman`, and `apk`
- deterministic test coverage exercises log collection and parsing on `journalctl`, `syslog`, and `dmesg`
- runtime status also reports detected MAC backends (`AppArmor`, `SELinux`, `sudo`) and container runtimes (`docker`, `podman`) when present
- privileged sections are `Logs`, `Security`, and `Audit`
- when backend access is partial or unavailable, Kinatio surfaces reduced-capability or deferred state instead of guessing

## Documentation

- [`docs/README.md`](docs/README.md) — documentation index
- [`QUICKSTART.md`](QUICKSTART.md) — install, first run, and common workflows
- [`docs/audits/`](docs/audits/) — homeplace for any audits done
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — contributor workflow
- [`SECURITY.md`](SECURITY.md) — vulnerability reporting guidance
- [`CHANGELOG.md`](CHANGELOG.md) — notable changes

## Development

```bash
./.venv/bin/ruff check kinatio tests
./.venv/bin/python3 -m pytest -q
```

## License

MIT — see [`LICENSE`](LICENSE).
