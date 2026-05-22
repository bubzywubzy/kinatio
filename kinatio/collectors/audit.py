"""Collector for SELinux, AppArmor, and auditd posture."""

from __future__ import annotations

import re
from pathlib import Path

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import AuditFinding, AuditState, AvailabilityInfo, CollectionAccessInfo, utc_now
from kinatio.execution.subprocess import SafeSubprocessRunner


class AuditCollector(Collector):
    name = "audit"
    subsystem = "audit"
    interval = 45.0

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> AuditState:
        del config
        selinux_enabled, selinux_mode = await self._collect_selinux(runner)
        apparmor_enabled, apparmor_profiles = await self._collect_apparmor(runner)
        auditd_active = await self._collect_auditd_state(runner)
        audit_status, audit_details, collection_access = await self._collect_auditctl_status(runner)
        findings = self._build_findings(
            selinux_enabled,
            selinux_mode,
            apparmor_enabled,
            auditd_active,
            audit_status,
            audit_details,
        )
        available = any(value is not None for value in (selinux_enabled, apparmor_enabled, auditd_active, audit_status))
        return AuditState(
            refreshed_at=utc_now(),
            selinux_enabled=selinux_enabled,
            selinux_mode=selinux_mode,
            apparmor_enabled=apparmor_enabled,
            apparmor_profiles_loaded=apparmor_profiles,
            auditd_active=auditd_active,
            audit_status=audit_status,
            audit_details=audit_details,
            findings=findings[:20],
            collection_access=collection_access,
            availability=AvailabilityInfo(
                available=available,
                reason=collection_access.detail if collection_access.detail else (
                    None if available else "No SELinux, AppArmor, or auditd backend was detected."
                ),
            ),
        )

    async def _collect_selinux(self, runner: SafeSubprocessRunner) -> tuple[bool | None, str | None]:
        result = await runner.run(["sestatus"], timeout=5.0, allow_missing=True)
        if result.missing_dependency or result.returncode != 0:
            return None, None
        enabled = None
        mode = None
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("SELinux status:"):
                enabled = stripped.partition(":")[2].strip().lower() == "enabled"
            elif stripped.startswith("Current mode:"):
                mode = stripped.partition(":")[2].strip().lower()
        return enabled, mode

    async def _collect_apparmor(self, runner: SafeSubprocessRunner) -> tuple[bool | None, int | None]:
        enabled_path = Path("/sys/module/apparmor/parameters/enabled")
        enabled = None
        if enabled_path.exists():
            try:
                enabled = enabled_path.read_text(encoding="utf-8").strip().lower().startswith("y")
            except OSError:
                enabled = None
        result = await runner.run(["aa-status"], timeout=8.0, allow_missing=True)
        if result.missing_dependency:
            return enabled, None
        profiles = None
        if result.returncode == 0:
            match = re.search(r"(\d+) profiles are loaded", result.stdout)
            if match:
                profiles = int(match.group(1))
            if enabled is None:
                enabled = True
        return enabled, profiles

    async def _collect_auditd_state(self, runner: SafeSubprocessRunner) -> bool | None:
        result = await runner.run(["systemctl", "is-active", "auditd.service"], timeout=5.0, allow_missing=True)
        if result.missing_dependency or result.returncode not in (0, 3):
            return None
        return result.stdout.strip() == "active"

    async def _collect_auditctl_status(
        self,
        runner: SafeSubprocessRunner,
    ) -> tuple[str | None, dict[str, str], CollectionAccessInfo]:
        elevated_result = await runner.run(
            ["auditctl", "-s"],
            timeout=5.0,
            allow_missing=True,
            prepend_sudo=True,
        )
        if elevated_result.returncode == 0 and not elevated_result.timed_out:
            audit_status, audit_details = self._parse_auditctl_status(elevated_result.stdout)
            return (
                audit_status,
                audit_details,
                CollectionAccessInfo(
                    requires_auth=True,
                    elevated=True,
                    detail="Collected auditctl status through the cached sudo session.",
                ),
            )

        if elevated_result.missing_dependency:
            return None, {}, CollectionAccessInfo(
                requires_auth=True,
                detail=elevated_result.stderr or "sudo is not installed.",
            )

        fallback_result = await runner.run(["auditctl", "-s"], timeout=5.0, allow_missing=True)
        if fallback_result.returncode == 0 and not fallback_result.timed_out:
            audit_status, audit_details = self._parse_auditctl_status(fallback_result.stdout)
            return (
                audit_status,
                audit_details,
                CollectionAccessInfo(
                    requires_auth=True,
                    partial=True,
                    detail=(
                        "Elevated auditctl access was unavailable during this refresh; "
                        "showing unprivileged status output."
                    ),
                ),
            )

        stderr = (fallback_result.stderr or elevated_result.stderr).strip()
        if stderr:
            return stderr.splitlines()[0], {}, CollectionAccessInfo(
                requires_auth=True,
                partial=True,
                detail="auditctl requires elevated privileges for full status on this host.",
            )
        return None, {}, CollectionAccessInfo(
            requires_auth=True,
            partial=True,
            detail="auditctl status was unavailable during this refresh.",
        )

    def _parse_auditctl_status(self, stdout: str) -> tuple[str | None, dict[str, str]]:
        details: dict[str, str] = {}
        first_line: str | None = None
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if first_line is None:
                first_line = stripped
            parts = stripped.split(None, 1)
            if len(parts) == 2:
                details[parts[0]] = parts[1]
        return first_line or "auditctl available", details

    def _build_findings(
        self,
        selinux_enabled: bool | None,
        selinux_mode: str | None,
        apparmor_enabled: bool | None,
        auditd_active: bool | None,
        audit_status: str | None,
        audit_details: dict[str, str],
    ) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        if selinux_enabled and selinux_mode == "permissive":
            findings.append(
                AuditFinding(
                    severity="warning",
                    title="SELinux is permissive",
                    detail="Mandatory access control is enabled but not enforcing policy decisions.",
                )
            )
        if selinux_enabled is False and apparmor_enabled is False:
            findings.append(
                AuditFinding(
                    severity="warning",
                    title="No mandatory access control backend is active",
                    detail="Neither SELinux nor AppArmor reported an active policy backend.",
                )
            )
        if auditd_active is False:
            findings.append(
                AuditFinding(
                    severity="warning",
                    title="auditd is inactive",
                    detail="Kernel audit events are not being persisted by the audit daemon.",
                )
            )
        if audit_details.get("enabled") == "0":
            findings.append(
                AuditFinding(
                    severity="warning",
                    title="Kernel auditing is disabled",
                    detail="auditctl reported that the kernel audit subsystem is currently disabled.",
                )
            )
        if audit_details.get("enabled") == "2":
            findings.append(
                AuditFinding(
                    severity="info",
                    title="Kernel auditing is immutable",
                    detail="auditctl reported immutable audit rules, which prevents runtime rule changes until reboot.",
                )
            )
        if audit_status and "permission denied" in audit_status.lower():
            findings.append(
                AuditFinding(
                    severity="info",
                    title="auditctl status requires elevated privileges",
                    detail="The collector could detect auditctl but needs privileges to read full status output.",
                )
            )
        if not findings:
            findings.append(
                AuditFinding(
                    severity="info",
                    title="Sampled audit backends responded normally",
                    detail="SELinux, AppArmor, and auditd checks did not surface immediate posture warnings.",
                )
            )
        return findings