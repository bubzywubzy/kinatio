"""Async collector scheduler."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime
from inspect import isawaitable

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import AvailabilityInfo, EventEntry, LogEntry
from kinatio.execution.subprocess import SafeSubprocessRunner
from kinatio.runtime.store import SystemStateStore


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CollectorScheduler:
    """Runs periodic and streaming collectors without blocking the UI."""

    def __init__(
        self,
        *,
        store: SystemStateStore,
        runner: SafeSubprocessRunner,
        collectors: Sequence[Collector],
        config: AppConfig,
        collection_gate: Callable[[Collector], AvailabilityInfo | None] | None = None,
    ) -> None:
        self.store = store
        self.runner = runner
        self.collectors = list(collectors)
        self.config = config
        self.collection_gate = collection_gate
        self._tasks: list[asyncio.Task[None]] = []
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        await asyncio.gather(*(self._collect_once(collector) for collector in self.collectors), return_exceptions=True)
        for collector in self.collectors:
            if collector.streaming:
                self._tasks.append(asyncio.create_task(self._run_stream(collector)))
            else:
                self._tasks.append(asyncio.create_task(self._run_periodic(collector)))

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def refresh_now(self, subsystem: str | None = None) -> None:
        if subsystem is None:
            targets = [collector for collector in self.collectors if not collector.streaming]
        else:
            targets = [collector for collector in self.collectors if collector.subsystem == subsystem]
        await asyncio.gather(*(self._collect_once(collector) for collector in targets), return_exceptions=True)

    def _deferred_availability(self, collector: Collector) -> AvailabilityInfo | None:
        if self.collection_gate is None:
            return None
        return self.collection_gate(collector)

    async def _run_periodic(self, collector: Collector) -> None:
        consecutive_failures = 0
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._periodic_delay(collector, consecutive_failures))
            except TimeoutError:
                pass
            if self._stop.is_set():
                return
            result = await self._collect_once(collector)
            consecutive_failures = self._next_failure_count(result, consecutive_failures)

    async def _run_stream(self, collector: Collector) -> None:
        consecutive_failures = 0
        while not self._stop.is_set():
            deferred = self._deferred_availability(collector)
            if deferred is not None:
                consecutive_failures = 0
                await self.store.update_health(
                    collector.name,
                    status="idle",
                    availability=deferred,
                    error=deferred.reason,
                    finished_at=_utcnow(),
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=collector.interval)
                except TimeoutError:
                    continue
                continue
            availability = collector.check_availability()
            await self.store.update_health(
                collector.name,
                status="running",
                availability=availability,
                started_at=_utcnow(),
            )
            if not availability.available:
                consecutive_failures = self._next_failure_count("unavailable", consecutive_failures)
                await self.store.update_health(
                    collector.name,
                    status="error",
                    availability=availability,
                    error=availability.reason,
                    finished_at=_utcnow(),
                )
                return
            try:
                stream = await self._resolve_stream(collector)
                async for entry in stream:
                    await self.store.append_log_entry(entry, self.config.max_log_entries)
                    if self._stop.is_set():
                        return
                if self._stop.is_set():
                    return
                error_message = "stream ended unexpectedly; retrying"
                await self.store.update_health(
                    collector.name,
                    status="error",
                    availability=availability,
                    error=error_message,
                    finished_at=_utcnow(),
                )
                await self.store.append_event(
                    EventEntry(
                        source=collector.name,
                        severity="error",
                        title="Streaming collector stopped",
                        details={"error": error_message, "subsystem": collector.subsystem},
                    )
                )
                consecutive_failures = self._next_failure_count("error", consecutive_failures)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._stream_retry_delay(consecutive_failures))
                except asyncio.CancelledError:
                    raise
                except TimeoutError:
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                consecutive_failures = self._next_failure_count("error", consecutive_failures)
                await self.store.update_health(
                    collector.name,
                    status="error",
                    availability=availability,
                    error=str(exc),
                    finished_at=_utcnow(),
                )
                await self.store.append_event(
                    EventEntry(
                        source=collector.name,
                        severity="error",
                        title="Streaming collector failed",
                        details={"error": str(exc)},
                    )
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._stream_retry_delay(consecutive_failures))
                except asyncio.CancelledError:
                    raise
                except TimeoutError:
                    continue

    async def _resolve_stream(self, collector: Collector) -> AsyncIterator[LogEntry]:
        stream = collector.stream(self.runner, self.config)
        if isawaitable(stream):
            stream = await stream
        if not hasattr(stream, "__aiter__"):
            raise TypeError(
                f"{collector.name}.stream() must return an async iterator, got {type(stream).__name__}"
            )
        return stream

    def _periodic_delay(self, collector: Collector, consecutive_failures: int) -> float:
        if consecutive_failures <= 0:
            return collector.interval
        return min(
            collector.interval * (2**consecutive_failures),
            self.config.collector_failure_backoff_max_interval,
        )

    def _stream_retry_delay(self, consecutive_failures: int) -> float:
        return min(
            self.config.stream_failure_backoff_base_interval * (2 ** max(consecutive_failures - 1, 0)),
            self.config.stream_failure_backoff_max_interval,
        )

    def _next_failure_count(self, result: str, consecutive_failures: int) -> int:
        if result == "ok":
            return 0
        if result in {"error", "unavailable"}:
            return consecutive_failures + 1
        return 0

    async def _collect_once(self, collector: Collector) -> str:
        started_at = _utcnow()
        deferred = self._deferred_availability(collector)
        if deferred is not None:
            await self.store.update_collection(
                collector.name,
                status="idle",
                availability=deferred,
                error=deferred.reason,
                started_at=started_at,
                finished_at=_utcnow(),
            )
            return "deferred"
        availability = collector.check_availability()
        await self.store.update_health(
            collector.name,
            status="running",
            availability=availability,
            started_at=started_at,
        )
        if not availability.available:
            await self.store.update_collection(
                collector.name,
                status="error",
                availability=availability,
                error=availability.reason,
                started_at=started_at,
                finished_at=_utcnow(),
            )
            return "unavailable"
        try:
            result = await collector.collect(self.runner, self.config)
            await self.store.update_collection(
                collector.name,
                subsystem=collector.subsystem,
                value=result,
                status="ok",
                availability=availability,
                started_at=started_at,
                finished_at=_utcnow(),
            )
            return "ok"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.store.update_collection(
                collector.name,
                status="error",
                availability=availability,
                error=str(exc),
                started_at=started_at,
                finished_at=_utcnow(),
            )
            await self.store.append_event(
                EventEntry(
                    source=collector.name,
                    severity="error",
                    title="Collector failure",
                    details={"error": str(exc), "subsystem": collector.subsystem},
                )
            )
            return "error"
