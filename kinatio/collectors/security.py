"""Collector for security posture and permission anomalies."""

from __future__ import annotations

import asyncio
import grp
import os
import pwd
import socket
from pathlib import Path

import psutil

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import CollectionAccessInfo, PortEntry, SecurityFinding, SecurityState, utc_now
from kinatio.execution.subprocess import SafeSubprocessRunner


class SecurityCollector(Collector):
    name = "security"
    subsystem = "security"
    interval = 30.0

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> SecurityState:
        sudo_probe = await runner.run(["sudo", "-n", "-v"], timeout=5.0, allow_missing=True)
        sudo_available = None if sudo_probe.missing_dependency else True
        sudo_authenticated = bool(sudo_available) and sudo_probe.returncode == 0 and not sudo_probe.timed_out

        sudo_result = await runner.run(["sudo", "-n", "-l"], timeout=5.0, allow_missing=True, prepend_sudo=False)
        sudo_non_interactive = (
            not sudo_result.missing_dependency
            and sudo_result.returncode == 0
            and not sudo_result.timed_out
        )
        findings = await asyncio.to_thread(self._scan_paths, config.anomaly_scan_paths)
        exposed = self._collect_exposed_services()
        groups = {group.gr_name: list(group.gr_mem) for group in grp.getgrall()}
        users = [entry.pw_name for entry in pwd.getpwall()]
        if sudo_available is None:
            findings.append(
                SecurityFinding(
                    severity="info",
                    title="sudo unavailable",
                    detail="Privileged controls are unavailable because sudo is not installed on this host.",
                )
            )
        elif not sudo_authenticated:
            findings.append(
                SecurityFinding(
                    severity="info",
                    title="sudo session locked",
                    detail="Privileged controls may require an interactive sudo unlock before elevated collection can run.",
                )
            )
        elif not sudo_non_interactive:
            findings.append(
                SecurityFinding(
                    severity="info",
                    title="sudo policy still requires interaction",
                    detail="The current sudo session is unlocked, but non-interactive policy inspection did not complete successfully.",
                )
            )
        return SecurityState(
            refreshed_at=utc_now(),
            sudo_available=sudo_available,
            sudo_authenticated=sudo_authenticated,
            sudo_non_interactive=sudo_non_interactive,
            sudo_configured=sudo_non_interactive,
            sudo_summary=(sudo_result.stdout or sudo_result.stderr or sudo_probe.stderr or sudo_probe.stdout).strip()[:400],
            users=users,
            groups=groups,
            findings=findings,
            exposed_services=exposed,
            collection_access=CollectionAccessInfo(
                requires_auth=True,
                detail=(
                    "The current security view remains a bounded posture sampler; unlock controls privileged access but most local scanning remains unprivileged."
                ),
            ),
        )

    def _scan_paths(self, paths: list[Path]) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        for path in paths:
            if not path.exists():
                findings.append(
                    SecurityFinding(
                        severity="warning",
                        title="Configured scan path missing",
                        detail="Configured anomaly scan path does not exist.",
                        path=str(path),
                    )
                )
                continue
            visited = 0
            for root, _, files in os.walk(path):
                for filename in files:
                    candidate = Path(root) / filename
                    try:
                        mode = candidate.stat().st_mode
                    except OSError:
                        continue
                    if mode & 0o002:
                        findings.append(
                            SecurityFinding(
                                severity="warning",
                                title="World-writable file",
                                detail="File is writable by any user.",
                                path=str(candidate),
                            )
                        )
                    if mode & 0o4000:
                        findings.append(
                            SecurityFinding(
                                severity="info",
                                title="Setuid file discovered",
                                detail="Review whether this binary should retain elevated privileges.",
                                path=str(candidate),
                            )
                        )
                    visited += 1
                    if visited >= 200:
                        break
                if visited >= 200:
                    break
        return findings[:100]

    def _collect_exposed_services(self) -> list[PortEntry]:
        ports: list[PortEntry] = []
        for connection in psutil.net_connections(kind="inet"):
            if connection.status != psutil.CONN_LISTEN or not connection.laddr:
                continue
            process_name = None
            if connection.pid:
                try:
                    process_name = psutil.Process(connection.pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    process_name = None
            ports.append(
                PortEntry(
                    protocol="tcp" if connection.type == socket.SOCK_STREAM else "udp",
                    local_address=connection.laddr.ip,
                    local_port=connection.laddr.port,
                    pid=connection.pid,
                    process_name=process_name,
                )
            )
        return sorted(ports, key=lambda entry: (entry.local_port, entry.local_address))[:100]
