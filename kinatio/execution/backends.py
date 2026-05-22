"""Backend detection and firewall helpers."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from kinatio.domain.models import AvailabilityInfo, FirewallState
from kinatio.execution.subprocess import CommandResult, SafeSubprocessRunner

CommandLocator = Callable[[str], str | None]
PathChecker = Callable[[Path], bool]

SERVICE_MANAGER_COMMANDS = {
    "systemd": "systemctl",
    "openrc": "rc-service",
    "runit": "sv",
    "sysvinit": "service",
}

LOG_BACKEND_COMMANDS = {
    "journalctl": "journalctl",
    "dmesg": "dmesg",
}


def detect_service_manager(
    precedence: list[str],
    *,
    which: CommandLocator = shutil.which,
    path_exists: PathChecker = Path.exists,
) -> str | None:
    sentinel_paths = {
        "systemd": (Path("/run/systemd/system"),),
        "openrc": (Path("/run/openrc"),),
        "runit": (Path("/run/runit"), Path("/etc/runit"), Path("/etc/service"), Path("/var/service")),
        "sysvinit": (Path("/etc/init.d"),),
    }
    for backend in precedence:
        if any(path_exists(path) for path in sentinel_paths.get(backend, ())):
            return backend
        command = SERVICE_MANAGER_COMMANDS.get(backend)
        if command and which(command):
            return backend
    return None


def detect_log_backend(
    precedence: list[str],
    *,
    which: CommandLocator = shutil.which,
    path_exists: PathChecker = Path.exists,
) -> str | None:
    syslog_paths = (Path("/var/log/syslog"), Path("/var/log/messages"))
    for backend in precedence:
        if backend == "syslog" and any(path_exists(path) for path in syslog_paths):
            return backend
        command = LOG_BACKEND_COMMANDS.get(backend)
        if command and which(command):
            return backend
    return None


def detect_firewall_backend(
    precedence: list[str],
    *,
    which: CommandLocator = shutil.which,
) -> str | None:
    checks = {
        "ufw": "ufw",
        "firewalld": "firewall-cmd",
        "nftables": "nft",
    }
    for backend in precedence:
        command = checks.get(backend)
        if command and which(command):
            return backend
    return None


def _parse_systemd_active_state(result: CommandResult) -> bool | None:
    if result.missing_dependency or result.timed_out:
        return None
    state = (result.stdout or result.stderr).strip().lower()
    if result.returncode == 0 and state == "active":
        return True
    if state in {"inactive", "failed"}:
        return False
    return None


def _is_permission_denied_detail(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        marker in lowered
        for marker in (
            "operation not permitted",
            "permission denied",
            "cache init failed",
        )
    )


def _truncate_firewall_summary(summary: str) -> str:
    return summary.strip()[:400]


def _parse_ufw_enabled(result: CommandResult) -> bool | None:
    if result.missing_dependency or result.timed_out:
        return None
    output = result.stdout.lower()
    if "status: active" in output:
        return True
    if "status: inactive" in output:
        return False
    return None


def _parse_firewalld_enabled(result: CommandResult) -> bool | None:
    if result.missing_dependency or result.timed_out:
        return None
    detail = (result.stdout or result.stderr).strip().lower()
    if result.returncode == 0 and "running" in detail:
        return True
    if "not running" in detail:
        return False
    return None


def _summarize_nftables_status(
    service_result: CommandResult,
    ruleset_result: CommandResult,
) -> str:
    service_detail = (service_result.stdout or service_result.stderr).strip()
    service_state = "" if service_result.missing_dependency or service_result.timed_out else service_detail
    ruleset_detail = (ruleset_result.stdout or ruleset_result.stderr).strip()

    if ruleset_result.returncode == 0 and ruleset_result.stdout.strip():
        return _truncate_firewall_summary(ruleset_result.stdout)

    if service_state and ruleset_detail and _is_permission_denied_detail(ruleset_detail):
        return _truncate_firewall_summary(
            f"nftables service state: {service_state}. Ruleset inspection requires elevated privileges: {ruleset_detail}"
        )

    if service_state:
        return _truncate_firewall_summary(f"nftables service state: {service_state}")

    if ruleset_detail:
        return _truncate_firewall_summary(ruleset_detail)

    if service_detail:
        return _truncate_firewall_summary(service_detail)

    return "nftables status was unavailable during this refresh."


async def read_firewall_status(
    runner: SafeSubprocessRunner,
    backend: str | None,
) -> FirewallState:
    if backend is None:
        return FirewallState(
            backend=None,
            enabled=None,
            summary="No supported firewall backend detected.",
            availability=AvailabilityInfo(available=False, reason="No firewall backend detected"),
        )
    if backend == "ufw":
        result = await runner.run(["ufw", "status"], timeout=5.0, allow_missing=True)
        summary = _truncate_firewall_summary((result.stdout or result.stderr).strip())
        return FirewallState(backend=backend, enabled=_parse_ufw_enabled(result), summary=summary)
    if backend == "firewalld":
        result = await runner.run(["firewall-cmd", "--state"], timeout=5.0, allow_missing=True)
        summary = _truncate_firewall_summary((result.stdout or result.stderr).strip())
        return FirewallState(backend=backend, enabled=_parse_firewalld_enabled(result), summary=summary)
    service_result = await runner.run(["systemctl", "is-active", "nftables.service"], timeout=5.0, allow_missing=True)
    ruleset_result = await runner.run(["nft", "list", "ruleset"], timeout=5.0, allow_missing=True)
    enabled = _parse_systemd_active_state(service_result)
    if enabled is None and ruleset_result.returncode == 0:
        enabled = bool(ruleset_result.stdout.strip())
    return FirewallState(
        backend=backend,
        enabled=enabled,
        summary=_summarize_nftables_status(service_result, ruleset_result),
    )
