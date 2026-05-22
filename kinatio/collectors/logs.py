"""Collector for Linux log backends, including live follow mode."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import AvailabilityInfo, CollectionAccessInfo, LogEntry, LogsState, utc_now
from kinatio.execution.backends import detect_log_backend
from kinatio.execution.subprocess import SafeSubprocessRunner


class LogsCollector(Collector):
    name = "logs"
    subsystem = "logs"
    interval = 20.0
    dependencies = ()
    streaming = True

    _SYSLOG_PATHS = (Path("/var/log/syslog"), Path("/var/log/messages"))

    def check_availability(self) -> AvailabilityInfo:
        backend = detect_log_backend(["journalctl", "syslog", "dmesg"])
        if backend is None:
            return AvailabilityInfo(
                available=False,
                reason="No supported log backend was detected.",
                dependency="log-backend",
            )
        return AvailabilityInfo(available=True, reason=f"Detected {backend}.", dependency=backend)

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> LogsState:
        backend = detect_log_backend(config.log_backend_precedence)
        if backend is None:
            return LogsState(
                refreshed_at=utc_now(),
                live_enabled=False,
                entries=[],
                collection_access=CollectionAccessInfo(requires_auth=True, detail="No supported log backend was detected."),
                availability=AvailabilityInfo(
                    available=False,
                    reason="No supported log backend was detected.",
                    dependency="log-backend",
                ),
            )

        if backend == "journalctl":
            output, access, availability = await self._collect_command_history(
                runner,
                command=["journalctl", "-n", str(config.log_history_lines), "-o", "json", "--no-pager"],
                dependency="journalctl",
                elevated_detail="Collected journal history through the cached sudo session.",
                partial_detail="Elevated journal access was unavailable during this refresh; showing the current user's accessible journal view.",
                unavailable_message="journalctl did not return log history during this refresh.",
            )
            entries = [entry async for entry in self._parse_journal_lines(output.splitlines())]
        elif backend == "dmesg":
            output, access, availability = await self._collect_command_history(
                runner,
                command=["dmesg", "--time-format", "iso", "--color=never"],
                dependency="dmesg",
                elevated_detail="Collected kernel ring buffer history through the cached sudo session.",
                partial_detail="Elevated kernel log access was unavailable during this refresh; showing the current user's accessible dmesg view.",
                unavailable_message="dmesg did not return kernel log history during this refresh.",
            )
            entries = [entry async for entry in self._parse_dmesg_lines(output.splitlines())]
        else:
            output, access, availability = await self._collect_syslog_history(runner, config.log_history_lines)
            entries = [entry async for entry in self._parse_syslog_lines(output.splitlines())]

        retained_entries = entries[-min(config.max_log_entries, config.log_history_lines) :]
        return LogsState(
            refreshed_at=utc_now(),
            entries=retained_entries,
            live_enabled=backend in {"journalctl", "syslog", "dmesg"},
            collection_access=access,
            availability=availability,
        )

    async def stream(
        self,
        runner: SafeSubprocessRunner,
        config: AppConfig,
    ) -> AsyncIterator[LogEntry]:
        backend = detect_log_backend(config.log_backend_precedence)
        if backend == "journalctl":
            async for line in runner.stream_lines(
                ["journalctl", "-f", "-o", "json", "--no-pager"],
                timeout=None,
                prepend_sudo=True,
            ):
                parsed = self._parse_journal_line(line)
                if parsed is not None:
                    yield parsed
            return

        if backend == "dmesg":
            async for line in runner.stream_lines(
                ["dmesg", "--follow", "--time-format", "iso", "--color=never"],
                timeout=None,
                prepend_sudo=True,
            ):
                parsed = self._parse_dmesg_line(line)
                if parsed is not None:
                    yield parsed
            return

        syslog_path = self._find_syslog_path()
        if backend == "syslog" and syslog_path is not None:
            async for line in runner.stream_lines(
                ["tail", "-n", "0", "-F", str(syslog_path)],
                timeout=None,
                prepend_sudo=True,
            ):
                parsed = self._parse_syslog_line(line)
                if parsed is not None:
                    yield parsed
            return

        raise FileNotFoundError("No supported streaming log backend is available")

    async def _collect_command_history(
        self,
        runner: SafeSubprocessRunner,
        *,
        command: list[str],
        dependency: str,
        elevated_detail: str,
        partial_detail: str,
        unavailable_message: str,
    ) -> tuple[str, CollectionAccessInfo, AvailabilityInfo]:
        elevated_result = await runner.run(command, timeout=12.0, allow_missing=True, prepend_sudo=True)
        if self._command_succeeded(elevated_result):
            return (
                elevated_result.stdout,
                CollectionAccessInfo(requires_auth=True, elevated=True, detail=elevated_detail),
                AvailabilityInfo(available=True, reason=elevated_detail, dependency=dependency),
            )

        fallback_result = await runner.run(command, timeout=12.0, allow_missing=True)
        if self._command_succeeded(fallback_result):
            return (
                fallback_result.stdout,
                CollectionAccessInfo(requires_auth=True, partial=True, detail=partial_detail),
                AvailabilityInfo(available=True, reason=partial_detail, dependency=dependency),
            )

        error_detail = (fallback_result.stderr or elevated_result.stderr or fallback_result.stdout).strip() or unavailable_message
        return (
            "",
            CollectionAccessInfo(requires_auth=True, partial=True, detail=error_detail),
            AvailabilityInfo(available=False, reason=error_detail, dependency=dependency),
        )

    async def _collect_syslog_history(
        self,
        runner: SafeSubprocessRunner,
        line_count: int,
    ) -> tuple[str, CollectionAccessInfo, AvailabilityInfo]:
        syslog_path = self._find_syslog_path()
        if syslog_path is None:
            return (
                "",
                CollectionAccessInfo(requires_auth=True, detail="No syslog file was detected on this host."),
                AvailabilityInfo(available=False, reason="No syslog file was detected on this host.", dependency="syslog"),
            )

        if shutil.which("tail"):
            return await self._collect_command_history(
                runner,
                command=["tail", "-n", str(line_count), str(syslog_path)],
                dependency="syslog",
                elevated_detail=f"Collected syslog history from {syslog_path} through the cached sudo session.",
                partial_detail=f"Elevated syslog access was unavailable during this refresh; showing the current user's accessible view of {syslog_path}.",
                unavailable_message=f"Unable to read syslog history from {syslog_path} during this refresh.",
            )

        try:
            lines = syslog_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            detail = f"Unable to read syslog history from {syslog_path}: {exc}"
            return (
                "",
                CollectionAccessInfo(requires_auth=True, partial=True, detail=detail),
                AvailabilityInfo(available=False, reason=detail, dependency="syslog"),
            )

        detail = f"Loaded syslog history from {syslog_path} without tail; elevated access was not required for this refresh."
        return (
            "\n".join(lines[-line_count:]),
            CollectionAccessInfo(requires_auth=True, partial=True, detail=detail),
            AvailabilityInfo(available=True, reason=detail, dependency="syslog"),
        )

    def _find_syslog_path(self) -> Path | None:
        for path in self._SYSLOG_PATHS:
            if path.exists():
                return path
        return None

    def _command_succeeded(self, result: object) -> bool:
        return bool(
            getattr(result, "returncode", None) == 0
            and not getattr(result, "timed_out", False)
        )

    async def _parse_journal_lines(self, lines: list[str]) -> AsyncIterator[LogEntry]:
        for line in lines:
            parsed = self._parse_journal_line(line)
            if parsed is not None:
                yield parsed

    async def _parse_dmesg_lines(self, lines: list[str]) -> AsyncIterator[LogEntry]:
        for line in lines:
            parsed = self._parse_dmesg_line(line)
            if parsed is not None:
                yield parsed

    async def _parse_syslog_lines(self, lines: list[str]) -> AsyncIterator[LogEntry]:
        for line in lines:
            parsed = self._parse_syslog_line(line)
            if parsed is not None:
                yield parsed

    def _parse_journal_line(self, line: str) -> LogEntry | None:
        if not line.strip():
            return None
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        realtime_timestamp = payload.get("__REALTIME_TIMESTAMP")
        timestamp = utc_now()
        if realtime_timestamp:
            try:
                timestamp = datetime.fromtimestamp(int(realtime_timestamp) / 1_000_000, tz=UTC)
            except (TypeError, ValueError, OSError):
                timestamp = utc_now()
        return LogEntry(
            timestamp=timestamp,
            source=payload.get("SYSLOG_IDENTIFIER", "journal"),
            unit=payload.get("_SYSTEMD_UNIT"),
            priority=str(payload.get("PRIORITY")) if payload.get("PRIORITY") is not None else None,
            message=payload.get("MESSAGE", ""),
        )

    def _parse_dmesg_line(self, line: str) -> LogEntry | None:
        stripped = line.strip()
        if not stripped:
            return None
        match = re.match(r"^\[(?P<stamp>[^\]]+)\]\s*(?P<message>.*)$", stripped)
        timestamp = utc_now()
        message = stripped
        if match:
            raw_stamp = match.group("stamp").replace(",", ".")
            message = match.group("message")
            try:
                parsed = datetime.fromisoformat(raw_stamp)
                timestamp = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
            except ValueError:
                timestamp = utc_now()
        return LogEntry(timestamp=timestamp, source="kernel", unit="kernel", message=message)

    def _parse_syslog_line(self, line: str) -> LogEntry | None:
        stripped = line.strip()
        if not stripped:
            return None
        pattern = re.match(
            r"^(?P<stamp>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+\S+\s+(?P<source>[^:]+):\s?(?P<message>.*)$",
            stripped,
        )
        timestamp = utc_now()
        source = "syslog"
        message = stripped
        if pattern:
            try:
                parsed = datetime.strptime(
                    f"{datetime.now(UTC).year} {pattern.group('stamp')}",
                    "%Y %b %d %H:%M:%S",
                )
                timestamp = parsed.replace(tzinfo=UTC)
            except ValueError:
                timestamp = utc_now()
            source = pattern.group("source").split("[", 1)[0].strip()
            message = pattern.group("message")
        return LogEntry(timestamp=timestamp, source=source or "syslog", unit=source or None, message=message)


