import asyncio

import pytest

from kinatio.collectors.logs import LogsCollector
from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import AvailabilityInfo, HardwareState, LogEntry, LogsState, SystemState
from kinatio.execution.subprocess import SafeSubprocessRunner
from kinatio.runtime.scheduler import CollectorScheduler
from kinatio.runtime.store import SystemStateStore


class _FakeHardwareCollector(Collector):
    name = "hardware"
    subsystem = "hardware"
    interval = 30.0

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> HardwareState:
        del runner, config
        return HardwareState()


async def test_scheduler_batches_successful_collection_write() -> None:
    store = SystemStateStore(SystemState())
    scheduler = CollectorScheduler(
        store=store,
        runner=SafeSubprocessRunner(),
        collectors=[_FakeHardwareCollector()],
        config=AppConfig(),
    )

    await scheduler.refresh_now()
    version, state = await store.snapshot()

    assert version == 2
    assert state.collector_health["hardware"].status == "ok"


async def test_scheduler_start_bootstraps_periodic_collectors_once() -> None:
    collector = _FakeHardwareCollector()
    store = SystemStateStore(SystemState())
    scheduler = CollectorScheduler(
        store=store,
        runner=SafeSubprocessRunner(),
        collectors=[collector],
        config=AppConfig(),
    )

    await scheduler.start()
    await asyncio.sleep(0)
    version, state = await store.snapshot()
    await scheduler.stop()

    assert version == 2
    assert state.collector_health["hardware"].status == "ok"


class _DeferredSecurityCollector(Collector):
    name = "security"
    subsystem = "security"
    interval = 30.0

    def __init__(self) -> None:
        self.collect_called = False

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> HardwareState:
        del runner, config
        self.collect_called = True
        return HardwareState()


async def test_scheduler_defers_collection_when_policy_blocks_subsystem() -> None:
    collector = _DeferredSecurityCollector()
    store = SystemStateStore(SystemState())
    scheduler = CollectorScheduler(
        store=store,
        runner=SafeSubprocessRunner(),
        collectors=[collector],
        config=AppConfig(),
        collection_gate=lambda current: AvailabilityInfo(
            available=False,
            reason="Collection deferred until sudo authentication is unlocked.",
            dependency="sudo",
        )
        if current.subsystem == "security"
        else None,
    )

    await scheduler.refresh_now(subsystem="security")
    version, state = await store.snapshot()

    assert version == 1
    assert collector.collect_called is False
    assert state.collector_health["security"].status == "idle"
    assert state.collector_health["security"].availability.available is False
    assert "deferred" in (state.collector_health["security"].availability.reason or "")


class _FakeStreamingRunner:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.commands: list[list[str]] = []

    async def run(self, command: list[str], **kwargs: object):  # pragma: no cover - not used in this test
        del command, kwargs
        raise AssertionError("run should not be used when testing stream iteration")

    async def stream_lines(self, command: list[str], **kwargs: object):
        del kwargs
        self.commands.append(command)
        for line in self.lines:
            yield line


class _FakeStreamingCollector(Collector):
    name = "logs"
    subsystem = "logs"
    interval = 30.0
    streaming = True

    def __init__(self) -> None:
        self.stream_started = asyncio.Event()
        self._hold_open = asyncio.Event()

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> LogsState:
        del runner, config
        return LogsState(entries=[])

    async def stream(self, runner: SafeSubprocessRunner, config: AppConfig):
        del runner, config
        self.stream_started.set()
        yield LogEntry(message="streamed line")
        await self._hold_open.wait()


class _AwaitableStreamCollector(Collector):
    name = "logs"
    subsystem = "logs"
    interval = 30.0
    streaming = True

    def __init__(self) -> None:
        self.stream_started = asyncio.Event()
        self._hold_open = asyncio.Event()

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> LogsState:
        del runner, config
        return LogsState(entries=[])

    async def stream(self, runner: SafeSubprocessRunner, config: AppConfig):
        del runner, config
        self.stream_started.set()
        return self._entries()

    async def _entries(self):
        yield LogEntry(message="awaited stream")
        await self._hold_open.wait()


class _ExplodingStreamingCollector(Collector):
    name = "logs"
    subsystem = "logs"
    interval = 30.0
    streaming = True

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> LogsState:
        del runner, config
        return LogsState(entries=[])

    async def stream(self, runner: SafeSubprocessRunner, config: AppConfig):
        del runner, config
        raise RuntimeError("boom")


class _ClosingStreamingCollector(Collector):
    name = "logs"
    subsystem = "logs"
    interval = 30.0
    streaming = True

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> LogsState:
        del runner, config
        return LogsState(entries=[])

    async def stream(self, runner: SafeSubprocessRunner, config: AppConfig):
        del runner, config
        yield LogEntry(message="closing stream")


async def test_logs_collector_stream_returns_async_iterator(monkeypatch) -> None:
    monkeypatch.setattr("kinatio.collectors.logs.detect_log_backend", lambda _precedence: "journalctl")
    collector = LogsCollector()
    runner = _FakeStreamingRunner(
        [
            '{"MESSAGE":"hello","SYSLOG_IDENTIFIER":"kernel","PRIORITY":6}',
            '{"MESSAGE":"bye","SYSLOG_IDENTIFIER":"sshd","PRIORITY":4}',
        ]
    )

    stream = collector.stream(runner, AppConfig())
    entries = [entry async for entry in stream]

    assert hasattr(stream, "__aiter__")
    assert [entry.message for entry in entries] == ["hello", "bye"]
    assert runner.commands == [["journalctl", "-f", "-o", "json", "--no-pager"]]


async def test_scheduler_runs_streaming_collectors_after_bootstrap() -> None:
    collector = _FakeStreamingCollector()
    store = SystemStateStore(SystemState())
    scheduler = CollectorScheduler(
        store=store,
        runner=SafeSubprocessRunner(),
        collectors=[collector],
        config=AppConfig(),
    )

    await scheduler.start()
    await asyncio.wait_for(collector.stream_started.wait(), timeout=1.0)
    await asyncio.sleep(0)
    version, state = await store.snapshot()
    await scheduler.stop()

    assert version >= 4
    assert any(entry.message == "streamed line" for entry in state.logs.entries)


async def test_scheduler_accepts_coroutine_wrapped_stream_iterators() -> None:
    collector = _AwaitableStreamCollector()
    store = SystemStateStore(SystemState())
    scheduler = CollectorScheduler(
        store=store,
        runner=SafeSubprocessRunner(),
        collectors=[collector],
        config=AppConfig(),
    )

    await scheduler.start()
    await asyncio.wait_for(collector.stream_started.wait(), timeout=1.0)
    await asyncio.sleep(0)
    version, state = await store.snapshot()
    await scheduler.stop()

    assert version >= 4
    assert any(entry.message == "awaited stream" for entry in state.logs.entries)


def test_scheduler_uses_bounded_backoff_for_repeated_failures() -> None:
    scheduler = CollectorScheduler(
        store=SystemStateStore(SystemState()),
        runner=SafeSubprocessRunner(),
        collectors=[_FakeHardwareCollector()],
        config=AppConfig(
            collector_failure_backoff_max_interval=20.0,
            stream_failure_backoff_base_interval=5.0,
            stream_failure_backoff_max_interval=12.0,
        ),
    )
    collector = _FakeHardwareCollector()
    collector.interval = 4.0

    assert scheduler._periodic_delay(collector, 0) == 4.0
    assert scheduler._periodic_delay(collector, 1) == 8.0
    assert scheduler._periodic_delay(collector, 3) == 20.0
    assert scheduler._stream_retry_delay(1) == 5.0
    assert scheduler._stream_retry_delay(2) == 10.0
    assert scheduler._stream_retry_delay(4) == 12.0


async def test_scheduler_re_raises_cancellation_during_stream_retry_wait(monkeypatch) -> None:
    collector = _ExplodingStreamingCollector()
    store = SystemStateStore(SystemState())
    scheduler = CollectorScheduler(
        store=store,
        runner=SafeSubprocessRunner(),
        collectors=[collector],
        config=AppConfig(stream_failure_backoff_base_interval=60.0, stream_failure_backoff_max_interval=60.0),
    )
    retry_wait_started = asyncio.Event()
    original_wait_for = asyncio.wait_for

    async def instrumented_wait_for(awaitable, timeout):
        if timeout == 60.0:
            retry_wait_started.set()
        return await original_wait_for(awaitable, timeout)

    monkeypatch.setattr("kinatio.runtime.scheduler.asyncio.wait_for", instrumented_wait_for)

    task = asyncio.create_task(scheduler._run_stream(collector))
    await asyncio.wait_for(retry_wait_started.wait(), timeout=1.0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_scheduler_marks_stream_eof_as_error_and_records_event() -> None:
    collector = _ClosingStreamingCollector()
    store = SystemStateStore(SystemState())
    scheduler = CollectorScheduler(
        store=store,
        runner=SafeSubprocessRunner(),
        collectors=[collector],
        config=AppConfig(stream_failure_backoff_base_interval=60.0, stream_failure_backoff_max_interval=60.0),
    )

    await scheduler.start()
    for _ in range(20):
        await asyncio.sleep(0)
        _, state = await store.snapshot()
        health = state.collector_health.get("logs")
        if health is not None and health.error:
            break
    else:
        raise AssertionError("stream EOF was not reflected in collector health")

    _, state = await store.snapshot()
    await scheduler.stop()

    assert any(entry.message == "closing stream" for entry in state.logs.entries)
    assert state.collector_health["logs"].status == "error"
    assert "ended unexpectedly" in (state.collector_health["logs"].error or "")
    assert any(event.title == "Streaming collector stopped" for event in state.events)