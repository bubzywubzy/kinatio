# Documentation

Kinatio keeps its package-facing entry points in the repository root and its longer operational and release-reference material under `docs/`.

## Start here

- [`../README.md`](../README.md) — concise project overview, install, and canonical command surface
- [`../QUICKSTART.md`](../QUICKSTART.md) — first-run workflow for the TUI and CLI
- [`../install.sh`](../install.sh) — cross-distro bootstrap for Fedora, Arch, and Debian-family Linux

## Release and follow-through

- [`audits/2026-05-readiness-audit.md`](audits/2026-05-readiness-audit.md) — current v1 evidence summary and release framing
- [`../CHANGELOG.md`](../CHANGELOG.md) — notable unreleased and released changes

## Project policies

- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — contributor workflow and local validation expectations
- [`../SECURITY.md`](../SECURITY.md) — private vulnerability reporting guidance

## Documentation policy

- Keep `README.md` concise and package-facing.
- Keep operational walkthroughs, release checklists, and long-form reference material under `docs/`.
- Keep audits and dated readiness records under `docs/audits/`.

## Current release posture

Kinatio is a v1 Linux system tooling project with an intentionally observe-only public surface. Public backend wording is kept to the paths backed by deterministic tests and current smoke evidence, and the release checklist now tracks ongoing v1 release follow-through work rather than gating the project’s version state.
