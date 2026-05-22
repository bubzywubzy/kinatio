# Security Policy

Kinatio can inspect privileged host state and cache sensitive snapshots, so security reports are handled as a first-class maintenance task.

## Supported versions

| Version | Supported |
| --- | --- |
| `main` | ✅ |
| latest tagged `1.x` release | ✅ |
| older `0.x` tags | ❌ |
| downstream forks or repackaged builds | ⚠️ best effort only |

## Reporting a vulnerability

Please use **GitHub private vulnerability reporting** for this repository whenever possible.

When you report an issue, include:

- Kinatio version or commit SHA
- Linux distribution and version
- detected backend(s), if relevant (`systemd`, OpenRC, `journalctl`, `ufw`, and so on)
- whether the issue requires sudo authentication, cached sudo state, or a specific privileged section
- a minimal reproduction case
- impact assessment and any logs or screenshots that help explain the problem

Please **do not** include:

- passwords, tokens, or API keys
- full copies of `/etc/sudoers`
- private hostnames, IPs, audit trails, or credentials unless they are redacted
- public exploit details before a fix or mitigation is available

## Response expectations

Targets for the initial response cadence are:

- acknowledgement within 3 business days
- triage status within 7 business days
- mitigation guidance or a fix plan as soon as reproduction is confirmed

The `1.x` release line normally ships fixes in the next suitable patch release unless coordinated disclosure or operational risk requires a different cadence.

## Scope notes

The highest-priority reports are issues that:

- bypass observe-only release constraints or re-enable host-mutating behavior without the expected safeguards
- weaken sudo authentication expectations or cache handling
- expose privileged data without the expected access checks or UI/CLI warnings
- allow shell injection or unsafe subprocess argument handling
- turn deferred privileged collection into silent or misleading partial success
