"""Collector for installed package inventory and sampled updates."""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterable

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import AvailabilityInfo, PackageEntry, PackagesState, utc_now
from kinatio.execution.subprocess import SafeSubprocessRunner


class PackagesCollector(Collector):
    name = "packages"
    subsystem = "packages"
    interval = 180.0

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> PackagesState:
        manager = self._detect_manager(config.package_manager_precedence)
        if manager is None:
            return PackagesState(
                refreshed_at=utc_now(),
                availability=AvailabilityInfo(available=False, reason="No supported package manager was detected."),
            )

        if manager == "dpkg":
            installed_count, entries = await self._collect_dpkg_inventory(runner, config.max_package_entries)
            update_count, updates = await self._collect_apt_updates(runner)
        elif manager == "rpm":
            installed_count, entries = await self._collect_rpm_inventory(runner, config.max_package_entries)
            update_count, updates = await self._collect_rpm_updates(runner)
        elif manager == "pacman":
            installed_count, entries = await self._collect_pacman_inventory(runner, config.max_package_entries)
            update_count, updates = await self._collect_pacman_updates(runner)
        else:
            installed_count, entries = await self._collect_apk_inventory(runner, config.max_package_entries)
            update_count, updates = await self._collect_apk_updates(runner)

        entries = self._prioritize_sample_entries(entries, updates, config.max_package_entries)
        await self._hydrate_entry_details(manager, runner, entries)
        for entry in entries:
            if entry.name in updates:
                entry.update_version = updates[entry.name]

        return PackagesState(
            refreshed_at=utc_now(),
            manager=manager,
            installed_count=installed_count,
            update_count=update_count,
            entries=entries,
        )

    def _detect_manager(self, precedence: list[str]) -> str | None:
        for manager in precedence:
            if manager == "dpkg" and shutil.which("dpkg-query"):
                return manager
            if manager == "rpm" and shutil.which("rpm"):
                return manager
            if manager == "pacman" and shutil.which("pacman"):
                return manager
            if manager == "apk" and shutil.which("apk"):
                return manager
        return None

    async def _collect_dpkg_inventory(self, runner: SafeSubprocessRunner, limit: int) -> tuple[int, list[PackageEntry]]:
        result = await runner.run(
            ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Architecture}\t${binary:Summary}\n"],
            timeout=20.0,
            allow_missing=True,
        )
        if result.missing_dependency or result.returncode != 0:
            return 0, []
        return self._parse_tsv_inventory(result.stdout, limit)

    async def _collect_apt_updates(self, runner: SafeSubprocessRunner) -> tuple[int | None, dict[str, str]]:
        if shutil.which("apt") is None:
            return None, {}
        result = await runner.run(["apt", "list", "--upgradable"], timeout=15.0, allow_missing=True)
        if result.missing_dependency or result.returncode != 0:
            return None, {}
        updates: dict[str, str] = {}
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("Listing"):
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            package_name = parts[0].split("/", 1)[0]
            updates[package_name] = parts[1]
        return len(updates), updates

    async def _collect_rpm_inventory(self, runner: SafeSubprocessRunner, limit: int) -> tuple[int, list[PackageEntry]]:
        result = await runner.run(
            ["rpm", "-qa", "--qf", r"%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SUMMARY}\n"],
            timeout=20.0,
            allow_missing=True,
        )
        if result.missing_dependency or result.returncode != 0:
            return 0, []
        return self._parse_tsv_inventory(result.stdout, limit)

    async def _collect_rpm_updates(self, runner: SafeSubprocessRunner) -> tuple[int | None, dict[str, str]]:
        command = None
        if shutil.which("dnf"):
            command = ["dnf", "-q", "check-update"]
        elif shutil.which("yum"):
            command = ["yum", "-q", "check-update"]
        if command is None:
            return None, {}
        result = await runner.run(command, timeout=20.0, allow_missing=True)
        if result.missing_dependency or result.returncode not in (0, 100):
            return None, {}
        updates: dict[str, str] = {}
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("Last metadata", "Obsoleting", "Security:")):
                continue
            parts = stripped.split()
            if len(parts) < 2 or parts[0].startswith("="):
                continue
            name = parts[0].rsplit(".", 1)[0]
            updates[name] = parts[1]
        return len(updates), updates

    async def _collect_pacman_inventory(self, runner: SafeSubprocessRunner, limit: int) -> tuple[int, list[PackageEntry]]:
        result = await runner.run(["pacman", "-Q"], timeout=20.0, allow_missing=True)
        if result.missing_dependency or result.returncode != 0:
            return 0, []
        entries: list[PackageEntry] = []
        count = 0
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(maxsplit=1)
            if len(parts) != 2:
                continue
            count += 1
            if len(entries) < limit:
                entries.append(PackageEntry(name=parts[0], version=parts[1]))
        return count, entries

    async def _collect_pacman_updates(self, runner: SafeSubprocessRunner) -> tuple[int | None, dict[str, str]]:
        result = await runner.run(["pacman", "-Qu"], timeout=20.0, allow_missing=True)
        if result.missing_dependency or result.returncode not in (0, 1):
            return None, {}
        updates: dict[str, str] = {}
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            updates[parts[0]] = parts[-1]
        return len(updates), updates

    async def _collect_apk_inventory(self, runner: SafeSubprocessRunner, limit: int) -> tuple[int, list[PackageEntry]]:
        result = await runner.run(["apk", "info", "-v"], timeout=20.0, allow_missing=True)
        if result.missing_dependency or result.returncode != 0:
            return 0, []
        entries: list[PackageEntry] = []
        count = 0
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            count += 1
            if len(entries) >= limit:
                continue
            match = re.match(r"^(.+)-([0-9][A-Za-z0-9._-]*)$", stripped)
            if match:
                name, version = match.groups()
            else:
                name, version = stripped, "unknown"
            entries.append(PackageEntry(name=name, version=version))
        return count, entries

    async def _collect_apk_updates(self, runner: SafeSubprocessRunner) -> tuple[int | None, dict[str, str]]:
        result = await runner.run(["apk", "version", "-l", "<"], timeout=20.0, allow_missing=True)
        if result.missing_dependency or result.returncode not in (0, 1):
            return None, {}
        updates: dict[str, str] = {}
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            name = parts[0]
            updates[name] = parts[-1] if len(parts) > 1 else "available"
        return len(updates), updates

    def _prioritize_sample_entries(
        self,
        entries: list[PackageEntry],
        updates: dict[str, str],
        limit: int,
    ) -> list[PackageEntry]:
        if limit <= 0:
            return []

        entries_by_name = {entry.name: entry for entry in entries}
        prioritized: list[PackageEntry] = []
        seen: set[str] = set()

        for name in sorted(updates, key=str.casefold):
            entry = entries_by_name.get(name)
            if entry is None:
                entry = PackageEntry(name=name, version="unknown", update_version=updates[name])
            else:
                entry.update_version = updates[name]
            prioritized.append(entry)
            seen.add(name)
            if len(prioritized) >= limit:
                return prioritized

        for entry in entries:
            if entry.name in seen:
                continue
            prioritized.append(entry)
            seen.add(entry.name)
            if len(prioritized) >= limit:
                break

        return prioritized

    async def _hydrate_entry_details(
        self,
        manager: str,
        runner: SafeSubprocessRunner,
        entries: list[PackageEntry],
    ) -> None:
        names = [entry.name for entry in entries if entry.name]
        if not names:
            return

        if manager == "dpkg":
            details = await self._collect_dpkg_details(runner, names)
        elif manager == "rpm":
            details = await self._collect_rpm_details(runner, names)
        elif manager == "pacman":
            details = await self._collect_pacman_details(runner, names)
        else:
            details = {}

        for entry in entries:
            detail = details.get(entry.name)
            if detail is None:
                continue
            if entry.version == "unknown" and detail.version != "unknown":
                entry.version = detail.version
            if entry.architecture is None and detail.architecture:
                entry.architecture = detail.architecture
            if entry.summary is None and detail.summary:
                entry.summary = detail.summary

    async def _collect_dpkg_details(
        self,
        runner: SafeSubprocessRunner,
        names: Iterable[str],
    ) -> dict[str, PackageEntry]:
        package_names = list(dict.fromkeys(names))
        if not package_names:
            return {}
        result = await runner.run(
            ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Architecture}\t${binary:Summary}\n", *package_names],
            timeout=20.0,
            allow_missing=True,
        )
        if result.missing_dependency or result.returncode != 0:
            return {}
        _, entries = self._parse_tsv_inventory(result.stdout, len(package_names))
        return {entry.name: entry for entry in entries}

    async def _collect_rpm_details(
        self,
        runner: SafeSubprocessRunner,
        names: Iterable[str],
    ) -> dict[str, PackageEntry]:
        package_names = list(dict.fromkeys(names))
        if not package_names:
            return {}
        result = await runner.run(
            ["rpm", "-q", "--qf", r"%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SUMMARY}\n", *package_names],
            timeout=20.0,
            allow_missing=True,
        )
        if result.missing_dependency or result.returncode != 0:
            return {}
        _, entries = self._parse_tsv_inventory(result.stdout, len(package_names))
        return {entry.name: entry for entry in entries}

    async def _collect_pacman_details(
        self,
        runner: SafeSubprocessRunner,
        names: Iterable[str],
    ) -> dict[str, PackageEntry]:
        package_names = list(dict.fromkeys(names))
        if not package_names:
            return {}
        result = await runner.run(["pacman", "-Qi", *package_names], timeout=20.0, allow_missing=True)
        if result.missing_dependency or result.returncode != 0:
            return {}

        details: dict[str, PackageEntry] = {}
        current: dict[str, str] = {}

        def commit() -> None:
            name = current.get("name")
            if not name:
                return
            details[name] = PackageEntry(
                name=name,
                version=current.get("version", "unknown"),
                architecture=current.get("architecture"),
                summary=current.get("description"),
            )

        for line in result.stdout.splitlines():
            stripped = line.rstrip()
            if not stripped:
                commit()
                current = {}
                continue
            if ":" not in stripped:
                continue
            field, value = stripped.split(":", 1)
            current[field.strip().lower()] = value.strip()
        commit()
        return details

    def _parse_tsv_inventory(self, output: str, limit: int) -> tuple[int, list[PackageEntry]]:
        entries: list[PackageEntry] = []
        count = 0
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split("\t")
            if len(parts) < 2:
                continue
            count += 1
            if len(entries) >= limit:
                continue
            architecture = parts[2] if len(parts) > 2 else None
            summary = parts[3] if len(parts) > 3 and parts[3] else None
            entries.append(PackageEntry(name=parts[0], version=parts[1], architecture=architecture, summary=summary))
        return count, entries