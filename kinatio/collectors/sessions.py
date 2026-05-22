"""Collector for active user sessions and recent login history."""

from __future__ import annotations

from datetime import UTC, datetime

import psutil

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import LoginHistoryEntry, SessionEntry, SessionsState, utc_now
from kinatio.execution.subprocess import SafeSubprocessRunner


class SessionsCollector(Collector):
    name = "sessions"
    subsystem = "sessions"
    interval = 20.0

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> SessionsState:
        current_sessions = self._collect_current_sessions(config.max_session_entries)
        recent_logins = await self._collect_recent_logins(runner, config.max_login_history)
        return SessionsState(
            refreshed_at=utc_now(),
            current_sessions=current_sessions,
            recent_logins=recent_logins,
        )

    def _collect_current_sessions(self, limit: int) -> list[SessionEntry]:
        entries: list[SessionEntry] = []
        for session in psutil.users():
            started_at = None
            if session.started:
                started_at = datetime.fromtimestamp(session.started, UTC)
            entries.append(
                SessionEntry(
                    username=session.name,
                    terminal=session.terminal,
                    host=session.host or None,
                    started_at=started_at,
                    pid=getattr(session, "pid", None),
                )
            )
        entries.sort(key=lambda entry: entry.started_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return entries[:limit]

    async def _collect_recent_logins(self, runner: SafeSubprocessRunner, limit: int) -> list[LoginHistoryEntry]:
        result = await runner.run(
            ["last", "--time-format", "iso", "-w", "-n", str(limit)],
            timeout=8.0,
            allow_missing=True,
        )
        if result.missing_dependency or result.returncode not in (0, 1):
            return []
        entries: list[LoginHistoryEntry] = []
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("wtmp begins"):
                continue
            tokens = stripped.split()
            if len(tokens) < 2:
                continue
            host = None
            if len(tokens) >= 3 and "T" not in tokens[2] and not tokens[2].startswith(("-", "(")):
                host = tokens[2]
            entries.append(
                LoginHistoryEntry(
                    username=tokens[0],
                    terminal=tokens[1],
                    host=host,
                    summary=stripped,
                )
            )
            if len(entries) >= limit:
                break
        return entries