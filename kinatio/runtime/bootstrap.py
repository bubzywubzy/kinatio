"""Shared runtime bootstrap helpers for the TUI and CLI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kinatio.collectors.audit import AuditCollector
from kinatio.collectors.base import Collector
from kinatio.collectors.containers import ContainersCollector
from kinatio.collectors.hardware import HardwareCollector
from kinatio.collectors.logs import LogsCollector
from kinatio.collectors.network import NetworkCollector
from kinatio.collectors.packages import PackagesCollector
from kinatio.collectors.power import PowerCollector
from kinatio.collectors.processes import ProcessesCollector
from kinatio.collectors.security import SecurityCollector
from kinatio.collectors.sessions import SessionsCollector
from kinatio.collectors.services import ServicesCollector
from kinatio.collectors.storage import StorageCollector
from kinatio.collectors.system import OSStateCollector
from kinatio.config import DEFAULT_CONFIG, AppConfig
from kinatio.domain.models import (
    AuditState,
    AvailabilityInfo,
    CollectionAccessInfo,
    CollectorHealth,
    LogsState,
    SecurityState,
    SystemState,
)
from kinatio.execution.auth import SudoAuthCoordinator, SudoAuthState
from kinatio.execution.subprocess import SafeSubprocessRunner
from kinatio.runtime.cache import JSONStateCache
from kinatio.runtime.context import detect_runtime_context
from kinatio.runtime.scheduler import CollectorScheduler
from kinatio.runtime.store import SystemStateStore

CollectionGate = Callable[[Collector], AvailabilityInfo | None]

LOCKED_PRIVILEGED_REASON = "Collection deferred until sudo authentication is unlocked."
LOCKED_PRIVILEGED_DETAIL = "Privileged data is hidden until sudo authentication is unlocked for the current session."
_LOCKED_PRIVILEGED_SUBSYSTEMS = ("logs", "security", "audit")


@dataclass(slots=True)
class RuntimeServices:
    """Shared runtime objects used by the Kinatio interfaces."""

    config: AppConfig
    store: SystemStateStore
    cache: JSONStateCache
    runner: SafeSubprocessRunner
    auth: SudoAuthCoordinator
    collectors: list[Collector]
    scheduler: CollectorScheduler


def _locked_privileged_availability() -> AvailabilityInfo:
    return AvailabilityInfo(
        available=False,
        reason=LOCKED_PRIVILEGED_REASON,
        dependency="sudo",
    )


def _locked_privileged_access() -> CollectionAccessInfo:
    return CollectionAccessInfo(
        requires_auth=True,
        detail=LOCKED_PRIVILEGED_DETAIL,
    )


def redact_privileged_state(state: SystemState) -> SystemState:
    """Remove cached privileged data when sudo is not currently unlocked."""

    redacted = state.model_copy(deep=True)
    redacted.logs = LogsState(
        live_enabled=False,
        collection_access=_locked_privileged_access(),
        availability=_locked_privileged_availability(),
    )
    redacted.security = SecurityState(
        collection_access=_locked_privileged_access(),
        availability=_locked_privileged_availability(),
    )
    redacted.audit = AuditState(
        collection_access=_locked_privileged_access(),
        availability=_locked_privileged_availability(),
    )
    for collector_name in _LOCKED_PRIVILEGED_SUBSYSTEMS:
        redacted.collector_health[collector_name] = CollectorHealth(
            collector=collector_name,
            availability=_locked_privileged_availability(),
        )
    return redacted


def state_for_persistence(state: SystemState) -> SystemState:
    """Prepare a snapshot for disk persistence without retaining privileged data."""

    return redact_privileged_state(state)


async def redact_locked_privileged_state(
    store: SystemStateStore,
    auth_state: SudoAuthState,
) -> None:
    """Fail closed by clearing cached privileged subsystems until unlock."""

    if auth_state.authenticated:
        return
    _, state = await store.snapshot()
    redacted = redact_privileged_state(state)
    if redacted.model_dump(mode="json") == state.model_dump(mode="json"):
        return
    await store.replace_state(redacted)


def build_collectors(config: AppConfig) -> list[Collector]:
    """Create collectors with their configured refresh intervals applied."""

    collectors: list[Collector] = [
        HardwareCollector(),
        OSStateCollector(),
        ProcessesCollector(),
        NetworkCollector(),
        ServicesCollector(),
        LogsCollector(),
        StorageCollector(),
        SecurityCollector(),
        SessionsCollector(),
        PowerCollector(),
        PackagesCollector(),
        AuditCollector(),
        ContainersCollector(),
    ]
    for collector in collectors:
        collector.interval = config.refresh_intervals.get(collector.subsystem, collector.interval)
    return collectors


def create_runtime_services(
    config: AppConfig | None = None,
    *,
    collection_gate: CollectionGate | None = None,
) -> RuntimeServices:
    """Construct the shared runtime services used by the UI and CLI."""

    resolved_config = config or DEFAULT_CONFIG
    store = SystemStateStore()
    cache = JSONStateCache(resolved_config.cache_path)
    runner = SafeSubprocessRunner()
    auth = SudoAuthCoordinator(runner)
    collectors = build_collectors(resolved_config)
    scheduler = CollectorScheduler(
        store=store,
        runner=runner,
        collectors=collectors,
        config=resolved_config,
        collection_gate=collection_gate,
    )
    return RuntimeServices(
        config=resolved_config,
        store=store,
        cache=cache,
        runner=runner,
        auth=auth,
        collectors=collectors,
        scheduler=scheduler,
    )


async def prime_runtime_store(services: RuntimeServices) -> None:
    """Load cached state and refresh detected runtime context into the store."""

    cached_state = services.cache.load()
    if cached_state is not None:
        await services.store.replace_state(state_for_persistence(cached_state))
    await refresh_runtime_context(services)


async def refresh_runtime_context(services: RuntimeServices) -> None:
    """Refresh detected runtime metadata in the shared store."""

    runtime_context, backend_status = detect_runtime_context(services.config)
    await services.store.update_runtime_context(runtime_context, backend_status)
