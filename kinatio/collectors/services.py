"""Collector for service-manager inventory across supported Linux backends."""

from __future__ import annotations

import re
from pathlib import Path

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import AvailabilityInfo, ServiceEntry, ServicesState, utc_now
from kinatio.execution.backends import detect_service_manager
from kinatio.execution.subprocess import SafeSubprocessRunner


class ServicesCollector(Collector):
    name = "services"
    subsystem = "services"
    interval = 12.0
    dependencies = ()

    _RUNIT_SERVICE_DIRS = (Path("/etc/service"), Path("/var/service"))

    def check_availability(self) -> AvailabilityInfo:
        backend = detect_service_manager(["systemd", "openrc", "runit", "sysvinit"])
        if backend is None:
            return AvailabilityInfo(
                available=False,
                reason="No supported service manager was detected.",
                dependency="service-manager",
            )
        return AvailabilityInfo(available=True, reason=f"Detected {backend}.", dependency=backend)

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> ServicesState:
        backend = detect_service_manager(config.service_manager_precedence)
        if backend is None:
            return ServicesState(
                refreshed_at=utc_now(),
                services=[],
                availability=AvailabilityInfo(
                    available=False,
                    reason="No supported service manager was detected.",
                    dependency="service-manager",
                ),
            )

        if backend == "systemd":
            services, availability = await self._collect_systemd(runner)
        elif backend == "openrc":
            services, availability = await self._collect_openrc(runner)
        elif backend == "runit":
            services, availability = await self._collect_runit(runner)
        else:
            services, availability = await self._collect_sysvinit(runner)

        services.sort(key=lambda service: (service.is_failed, service.active_state == "active", service.name), reverse=True)
        return ServicesState(refreshed_at=utc_now(), manager=backend, services=services, availability=availability)

    async def _collect_systemd(
        self,
        runner: SafeSubprocessRunner,
    ) -> tuple[list[ServiceEntry], AvailabilityInfo]:
        units_result = await runner.run(
            ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--plain", "--no-legend"],
            timeout=10.0,
            allow_missing=True,
        )
        unit_files_result = await runner.run(
            ["systemctl", "list-unit-files", "--type=service", "--no-pager", "--plain", "--no-legend"],
            timeout=10.0,
            allow_missing=True,
        )
        if units_result.missing_dependency:
            return [], AvailabilityInfo(
                available=False,
                reason=units_result.stderr or "Missing dependency: systemctl",
                dependency="systemctl",
            )
        unit_files = self._parse_unit_files(unit_files_result.stdout)
        services = self._parse_units(units_result.stdout, unit_files)
        return services, AvailabilityInfo(available=True, reason="Collected service inventory from systemd.", dependency="systemd")

    async def _collect_openrc(
        self,
        runner: SafeSubprocessRunner,
    ) -> tuple[list[ServiceEntry], AvailabilityInfo]:
        result = await runner.run(["rc-status", "--all"], timeout=10.0, allow_missing=True)
        if result.missing_dependency:
            return [], AvailabilityInfo(
                available=False,
                reason=result.stderr or "Missing dependency: rc-status",
                dependency="rc-status",
            )
        if result.returncode != 0 and not result.stdout.strip():
            return [], AvailabilityInfo(
                available=False,
                reason=(result.stderr or result.stdout).strip() or "OpenRC status inventory failed.",
                dependency="openrc",
            )
        return self._parse_openrc_status(result.stdout), AvailabilityInfo(
            available=True,
            reason="Collected service inventory from OpenRC.",
            dependency="openrc",
        )

    async def _collect_runit(
        self,
        runner: SafeSubprocessRunner,
    ) -> tuple[list[ServiceEntry], AvailabilityInfo]:
        service_dirs = [path for root in self._RUNIT_SERVICE_DIRS if root.exists() for path in sorted(root.iterdir()) if path.is_dir()]
        if not service_dirs:
            return [], AvailabilityInfo(
                available=True,
                reason="Detected runit but no service directories were found.",
                dependency="runit",
            )
        services: list[ServiceEntry] = []
        missing_dependency = False
        for service_dir in service_dirs:
            result = await runner.run(["sv", "status", str(service_dir)], timeout=5.0, allow_missing=True)
            if result.missing_dependency:
                missing_dependency = True
                break
            services.append(self._parse_runit_status(service_dir.name, result.stdout or result.stderr))
        if missing_dependency:
            return [], AvailabilityInfo(
                available=False,
                reason="Missing dependency: sv",
                dependency="sv",
            )
        return services, AvailabilityInfo(
            available=True,
            reason="Collected service inventory from runit.",
            dependency="runit",
        )

    async def _collect_sysvinit(
        self,
        runner: SafeSubprocessRunner,
    ) -> tuple[list[ServiceEntry], AvailabilityInfo]:
        result = await runner.run(["service", "--status-all"], timeout=10.0, allow_missing=True)
        if result.missing_dependency:
            return [], AvailabilityInfo(
                available=False,
                reason=result.stderr or "Missing dependency: service",
                dependency="service",
            )
        if result.returncode != 0 and not result.stdout.strip():
            return [], AvailabilityInfo(
                available=False,
                reason=(result.stderr or result.stdout).strip() or "SysV-init status inventory failed.",
                dependency="sysvinit",
            )
        return self._parse_sysv_status(result.stdout), AvailabilityInfo(
            available=True,
            reason="Collected service inventory from sysvinit.",
            dependency="sysvinit",
        )

    def _parse_unit_files(self, stdout: str) -> dict[str, str]:
        unit_files: dict[str, str] = {}
        for line in stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].endswith(".service"):
                unit_files[parts[0]] = parts[1].strip()
        return unit_files

    def _parse_units(self, stdout: str, unit_files: dict[str, str]) -> list[ServiceEntry]:
        services: list[ServiceEntry] = []
        for line in stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5 or not parts[0].endswith(".service"):
                continue
            unit_file_state = unit_files.get(parts[0], "unknown")
            services.append(
                ServiceEntry(
                    name=parts[0],
                    load_state=parts[1],
                    active_state=parts[2],
                    sub_state=parts[3],
                    description=parts[4],
                    unit_file_state=unit_file_state,
                    is_failed=parts[2] == "failed",
                    is_enabled=unit_file_state in {"enabled", "enabled-runtime", "linked", "linked-runtime"},
                )
            )
        return services

    def _parse_openrc_status(self, stdout: str) -> list[ServiceEntry]:
        services: list[ServiceEntry] = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("Runlevel:", "Dynamic", " * ")):
                continue
            if "[" not in stripped or "]" not in stripped:
                continue
            name, _, remainder = stripped.partition("[")
            status = remainder.partition("]")[0].strip().lower()
            service_name = name.strip()
            if not service_name:
                continue
            active_state, sub_state, is_failed = self._service_state_from_status(status)
            services.append(
                ServiceEntry(
                    name=service_name,
                    load_state="loaded",
                    active_state=active_state,
                    sub_state=sub_state,
                    description="OpenRC service",
                    unit_file_state="managed",
                    is_failed=is_failed,
                    is_enabled=True,
                )
            )
        return services

    def _parse_runit_status(self, service_name: str, output: str) -> ServiceEntry:
        line = next((entry.strip() for entry in output.splitlines() if entry.strip()), "")
        status_text = line.lower()
        if status_text.startswith("run:"):
            active_state = "active"
            sub_state = "running"
            is_failed = False
        elif status_text.startswith("down:"):
            active_state = "inactive"
            sub_state = "down"
            is_failed = False
        elif status_text.startswith("finish:"):
            active_state = "failed"
            sub_state = "finish"
            is_failed = True
        else:
            active_state = "unknown"
            sub_state = "unknown"
            is_failed = False
        return ServiceEntry(
            name=service_name,
            load_state="loaded",
            active_state=active_state,
            sub_state=sub_state,
            description=line or "runit service",
            unit_file_state="managed",
            is_failed=is_failed,
            is_enabled=True,
        )

    def _parse_sysv_status(self, stdout: str) -> list[ServiceEntry]:
        services: list[ServiceEntry] = []
        pattern = re.compile(r"^\[\s*([+\-?])\s*\]\s+(.+)$")
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            match = pattern.match(stripped)
            if not match:
                continue
            marker, service_name = match.groups()
            service_name = service_name.strip()
            if marker == "+":
                active_state, sub_state, is_failed = "active", "running", False
            elif marker == "-":
                active_state, sub_state, is_failed = "inactive", "stopped", False
            else:
                active_state, sub_state, is_failed = "unknown", "unknown", False
            services.append(
                ServiceEntry(
                    name=service_name,
                    load_state="loaded",
                    active_state=active_state,
                    sub_state=sub_state,
                    description="SysV init service",
                    unit_file_state="managed",
                    is_failed=is_failed,
                    is_enabled=marker != "?",
                )
            )
        return services

    def _service_state_from_status(self, status: str) -> tuple[str, str, bool]:
        if status in {"started", "starting", "online"}:
            return "active", status, False
        if status in {"stopped", "inactive"}:
            return "inactive", status, False
        if status in {"crashed", "failed"}:
            return "failed", status, True
        return "unknown", status or "unknown", False
