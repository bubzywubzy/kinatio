"""Centralized in-memory system state store."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from kinatio.domain.models import (
    AvailabilityInfo,
    CollectorHealth,
    EventEntry,
    LogEntry,
    RuntimeContext,
    SystemState,
)


def _timestamp() -> datetime:
    return datetime.now(UTC)


_STATE_SUBSYSTEMS = frozenset(
    {
        "hardware",
        "os_state",
        "processes",
        "network",
        "services",
        "logs",
        "storage",
        "security",
        "sessions",
        "power",
        "packages",
        "audit",
        "containers",
        "runtime",
    }
)


@dataclass(slots=True, frozen=True)
class StoreChange:
    """Summarizes what changed in the store since a prior version."""

    version: int
    changed_subsystems: frozenset[str] = frozenset()
    changed_collectors: frozenset[str] = frozenset()
    events_changed: bool = False
    backend_status_changed: bool = False


class SystemStateStore:
    """Owns the latest normalized system state."""

    def __init__(self, initial_state: SystemState | None = None) -> None:
        self._state = initial_state or SystemState()
        self._version = 0
        self._last_change = StoreChange(version=0)
        self._lock = asyncio.Lock()
        self._changed = asyncio.Event()

    def _signal_change_locked(
        self,
        *,
        changed_subsystems: frozenset[str] = frozenset(),
        changed_collectors: frozenset[str] = frozenset(),
        events_changed: bool = False,
        backend_status_changed: bool = False,
    ) -> None:
        self._version += 1
        self._last_change = StoreChange(
            version=self._version,
            changed_subsystems=changed_subsystems,
            changed_collectors=changed_collectors,
            events_changed=events_changed,
            backend_status_changed=backend_status_changed,
        )
        changed = self._changed
        self._changed = asyncio.Event()
        changed.set()

    def _build_health(
        self,
        collector_name: str,
        *,
        status: str,
        availability: AvailabilityInfo | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> CollectorHealth:
        health = self._state.collector_health
        previous = health.get(collector_name) or CollectorHealth(collector=collector_name)
        duration_ms = None
        if started_at and finished_at:
            duration_ms = (finished_at - started_at).total_seconds() * 1000
        last_completed_status = previous.last_completed_status
        if status == "ok":
            last_completed_status = "ok"
        elif status == "error":
            last_completed_status = "error"
        health[collector_name] = previous.model_copy(
            update={
                "status": status,
                "last_completed_status": last_completed_status,
                "availability": availability or previous.availability,
                "error": error,
                "last_started_at": started_at or previous.last_started_at,
                "last_finished_at": finished_at or previous.last_finished_at,
                "duration_ms": previous.duration_ms if duration_ms is None else duration_ms,
            }
        )
        return health[collector_name]

    def _set_state_timestamp_locked(self) -> None:
        self._state.timestamp = _timestamp()

    def _append_bounded_locked(self, items: list[Any], item: Any, limit: int) -> None:
        if limit <= 0:
            items.clear()
            return
        items.append(item)
        overflow = len(items) - limit
        if overflow > 0:
            del items[:overflow]

    async def snapshot(self) -> tuple[int, SystemState]:
        async with self._lock:
            return self._version, self._state.model_copy(deep=True)

    async def wait_for_change_notice(
        self,
        version: int,
        timeout: float | None = None,
    ) -> StoreChange:
        while True:
            async with self._lock:
                if self._version > version:
                    return self._last_change
                waiter = self._changed
            if timeout is None:
                await waiter.wait()
                continue
            try:
                await asyncio.wait_for(waiter.wait(), timeout=timeout)
            except TimeoutError:
                async with self._lock:
                    if self._version > version:
                        return self._last_change
                    return StoreChange(version=self._version)

    async def replace_state(self, new_state: SystemState) -> None:
        async with self._lock:
            self._state = new_state
            self._set_state_timestamp_locked()
            self._signal_change_locked(
                changed_subsystems=_STATE_SUBSYSTEMS,
                changed_collectors=frozenset(self._state.collector_health),
                events_changed=True,
                backend_status_changed=True,
            )

    async def update_subsystem(self, subsystem: str, value: BaseModel) -> None:
        async with self._lock:
            setattr(self._state, subsystem, value)
            self._set_state_timestamp_locked()
            self._signal_change_locked(changed_subsystems=frozenset({subsystem}))

    async def update_collection(
        self,
        collector_name: str,
        *,
        subsystem: str | None = None,
        value: BaseModel | None = None,
        status: str,
        availability: AvailabilityInfo | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        async with self._lock:
            self._build_health(
                collector_name,
                status=status,
                availability=availability,
                error=error,
                started_at=started_at,
                finished_at=finished_at,
            )
            if subsystem is not None and value is not None:
                setattr(self._state, subsystem, value)
            self._set_state_timestamp_locked()
            self._signal_change_locked(
                changed_subsystems=frozenset({subsystem}) if subsystem is not None else frozenset(),
                changed_collectors=frozenset({collector_name}),
            )

    async def update_health(
        self,
        collector_name: str,
        *,
        status: str,
        availability: AvailabilityInfo | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        async with self._lock:
            self._build_health(
                collector_name,
                status=status,
                availability=availability,
                error=error,
                started_at=started_at,
                finished_at=finished_at,
            )
            self._signal_change_locked(changed_collectors=frozenset({collector_name}))

    async def set_backend_status(self, backend: str, availability: AvailabilityInfo) -> None:
        async with self._lock:
            self._state.backend_status[backend] = availability
            self._signal_change_locked(
                changed_subsystems=frozenset({"runtime"}),
                backend_status_changed=True,
            )

    async def update_runtime_context(
        self,
        runtime: RuntimeContext,
        backend_status: dict[str, AvailabilityInfo],
    ) -> None:
        async with self._lock:
            self._state.runtime = runtime
            self._state.backend_status = backend_status.copy()
            self._set_state_timestamp_locked()
            self._signal_change_locked(
                changed_subsystems=frozenset({"runtime"}),
                backend_status_changed=True,
            )

    async def append_event(self, event: EventEntry, limit: int = 250) -> None:
        async with self._lock:
            self._append_bounded_locked(self._state.events, event, limit)
            self._set_state_timestamp_locked()
            self._signal_change_locked(events_changed=True)

    async def append_log_entry(self, entry: LogEntry, max_entries: int) -> None:
        async with self._lock:
            self._append_bounded_locked(self._state.logs.entries, entry, max_entries)
            self._state.logs.refreshed_at = _timestamp()
            self._set_state_timestamp_locked()
            self._signal_change_locked(changed_subsystems=frozenset({"logs"}))

    async def wait_for_change(self, version: int, timeout: float | None = None) -> tuple[int, SystemState]:
        while True:
            async with self._lock:
                if self._version > version:
                    return self._version, self._state.model_copy(deep=True)
                waiter = self._changed
            if timeout is None:
                await waiter.wait()
            else:
                try:
                    await asyncio.wait_for(waiter.wait(), timeout=timeout)
                except TimeoutError:
                    return await self.snapshot()
