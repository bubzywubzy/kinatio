# Kinatio readiness audit — 2026-05

_Date:_ 2026-05-21  
_Scope:_ observe-only boundary cleanup, backend-support proof review, docs-to-code parity, and v1 release framing for the current public surface.

## Executive summary

Kinatio is a coherent, tested Linux system tooling project with a clear observe-only public surface across its TUI and CLI. The command surface, section metadata, privilege model, package metadata, and CI expectations are all concrete enough to document precisely.

Kinatio now ships as a v1 observe-only Linux system tooling project with test-backed backend breadth and a clearly bounded public surface across its TUI and CLI.

## Validation snapshot for this readiness pass

The following checks were rerun during the observe-only cleanup, backend-matrix expansion, and docs refresh:

| Check | Result | Notes |
| --- | --- | --- |
| Relative Markdown links | **Pass** | Public docs and transition pointers resolve to existing files. |
| Lint (`./.venv/bin/ruff check kinatio tests`) | **Pass** | All checks passed. |
| Tests (`./.venv/bin/python -m pytest -q`) | **Pass** | `235 passed in 5.16s` |
| Smoke: `kinatio sections` | **Pass** | Listed 18 CLI-visible scan sections. |
| Smoke: `kinatio status --json` | **Pass** | Runtime context and deferred privileged collectors rendered correctly. |
| Smoke: `kinatio scan system --json` | **Pass** | System identity and uptime rendered successfully. |
| Smoke: `kinatio scan firewall --json` | **Pass** | Firewall posture rendered successfully on the detected backend. |
| Smoke: `kinatio scan logs --json` with locked sudo | **Pass** | Deferred privileged behavior rendered explicitly. |

Unlocked sudo verification was not completed on a release host in this pass and remains part of the release checklist.

## Verified product surface

The current public interface documented from code is:

- `kinatio` — default Textual TUI launch
- `kinatio tui` — explicit TUI launch
- `kinatio sections` — scan target discovery
- `kinatio status` — runtime, backend, and collector health
- `kinatio scan ...` — canonical non-interactive reporting interface

Additional verified behavior:

- `--follow` is only supported for `kinatio scan logs`
- privileged sections are `Logs`, `Security`, and `Audit`
- Linux is the supported platform
- Python `3.12+` is the supported interpreter floor
- the current public CLI/TUI surface is observe-only
- public backend wording is now limited to branches backed by deterministic tests and current smoke evidence

Backend evidence refreshed in this pass includes:

- service-manager detection and inventory branches for `systemd`, OpenRC, runit, and SysV-style hosts
- firewall detection and read-only status branches for `ufw`, `firewalld`, and `nftables`
- package inventory and update parsing branches for `dpkg`, `rpm`, `pacman`, and `apk`
- runtime-context detection for log backends, security backends, and container runtimes used in the public status surface

## Remaining post-v1 follow-through work

The repository now supports a v1 claim, but a few release follow-through tasks still remain:

- privileged locked/unlocked behavior still needs explicit release-host closure
- the release checklist and release-note cut still need to be completed as part of an actual launch

Those items are operational follow-through tasks, not blockers to describing the shipped project state as v1.

## Documentation decisions made in this pass

- the root `README.md` is kept concise and package-facing
- long-form release-reference material lives under `docs/`, while `QUICKSTART.md` remains a root package-facing walkthrough
- public wording stays aligned to the current observe-only product surface and does not advertise dormant internal action helpers as supported commands
- support wording is limited to the backend branches backed by deterministic tests and fresh smoke evidence

## Current recommendation

Use the following public positioning for the current release line:

> Kinatio is a v1 Linux observability and reporting console with an observe-only public surface and test-backed backend coverage for the currently documented paths.

The remaining checklist items should be treated as release follow-through work for the v1 line rather than as blockers to the version designation itself.
