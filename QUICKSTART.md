# Quick Start

## Requirements

- Linux
- Python `3.12+`
- a terminal that can run Textual applications

## Install

```bash
./install.sh
```

For contributor workflows and local validation tools:

```bash
./install.sh --dev
```

Manual fallback when `python3` is already `3.12+`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Launch the TUI

```bash
kinatio
```

No-argument `kinatio` starts the Textual interface.

Use the explicit form when you want it spelled out in scripts or notes:

```bash
kinatio tui
```

## First CLI commands

List the available scan targets:

```bash
kinatio sections
```

Inspect runtime, backend, and collector health:

```bash
kinatio status
kinatio status --json
```

Run a first system scan:

```bash
kinatio scan system
kinatio scan system --json
```

Run a broader multi-section report:

```bash
kinatio scan system network storage
kinatio scan all --json --output kinatio-report.json
```

Inspect firewall posture without mutating host state:

```bash
kinatio scan firewall
kinatio scan firewall --json
```

## Privileged sections

Kinatio defers privileged collection until sudo authentication is available for these sections:

- `Logs`
- `Security`
- `Audit`

Unlock and collect a privileged section explicitly:

```bash
kinatio scan logs --unlock
kinatio scan audit --unlock
```

Live follow is supported for logs only:

```bash
kinatio scan logs --follow --unlock
```

If you prefer to warm the sudo cache before launch:

```bash
sudo -v
kinatio
```

When privileged collection succeeds, Kinatio reports that the data was gathered through the cached sudo session. When access is partial or unavailable, the CLI and TUI surface that reduced-capability state explicitly.

## Cache reset

Kinatio stores cached state at `~/.cache/kinatio/state.json`.

Delete it safely to reset local state:

```bash
rm -f ~/.cache/kinatio/state.json
```

## Development checks

Run the documented quality gates locally:

```bash
./.venv/bin/ruff check kinatio tests
./.venv/bin/python3 -m pytest -q
```

## Release model

Kinatio now ships as an observe-only v1 release. The TUI and CLI report host state, health, and posture, but they do not expose host-mutating commands in the public interface.

The strongest release-host smoke path remains mainstream Linux systems with `systemd` and `journalctl`, while broader backend branches are described conservatively and backed by deterministic tests rather than broader release-host validation claims.
