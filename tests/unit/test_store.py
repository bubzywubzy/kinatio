from datetime import UTC, datetime

from kinatio.domain.models import AvailabilityInfo, EventEntry, HardwareState, RuntimeContext, SystemState
from kinatio.runtime.store import SystemStateStore


async def test_store_updates_subsystem() -> None:
    store = SystemStateStore(SystemState())

    await store.update_subsystem("hardware", HardwareState())

    version, state = await store.snapshot()

    assert version == 1
    assert state.hardware is not None


async def test_store_update_collection_batches_health_and_subsystem() -> None:
    store = SystemStateStore(SystemState())
    started_at = datetime.now(UTC)

    await store.update_collection(
        "hardware",
        subsystem="hardware",
        value=HardwareState(),
        status="ok",
        availability=AvailabilityInfo(available=True),
        started_at=started_at,
        finished_at=started_at,
    )

    version, state = await store.snapshot()

    assert version == 1
    assert state.hardware is not None
    assert state.collector_health["hardware"].status == "ok"


async def test_store_updates_runtime_context_and_backend_statuses() -> None:
    store = SystemStateStore(SystemState())

    await store.update_runtime_context(
        RuntimeContext(distro_name="Fedora Linux", package_manager="rpm", service_manager="systemd"),
        {
            "package_manager": AvailabilityInfo(available=True, reason="Detected rpm."),
            "service_manager": AvailabilityInfo(available=True, reason="Detected systemd."),
        },
    )

    version, state = await store.snapshot()

    assert version == 1
    assert state.runtime.distro_name == "Fedora Linux"
    assert state.runtime.package_manager == "rpm"
    assert state.backend_status["service_manager"].available is True


async def test_store_preserves_zero_duration_measurements() -> None:
    store = SystemStateStore(SystemState())
    started_at = datetime.now(UTC)

    await store.update_collection(
        "hardware",
        subsystem="hardware",
        value=HardwareState(),
        status="ok",
        availability=AvailabilityInfo(available=True),
        started_at=started_at,
        finished_at=started_at,
    )

    _, state = await store.snapshot()

    assert state.collector_health["hardware"].duration_ms == 0.0


async def test_store_preserves_last_completed_status_while_refresh_is_running() -> None:
    store = SystemStateStore(SystemState())
    started_at = datetime.now(UTC)

    await store.update_collection(
        "hardware",
        subsystem="hardware",
        value=HardwareState(),
        status="ok",
        availability=AvailabilityInfo(available=True),
        started_at=started_at,
        finished_at=started_at,
    )
    await store.update_health(
        "hardware",
        status="running",
        availability=AvailabilityInfo(available=True),
        started_at=started_at,
    )

    _, state = await store.snapshot()

    assert state.collector_health["hardware"].status == "running"
    assert state.collector_health["hardware"].last_completed_status == "ok"


async def test_store_wait_for_change_notice_reports_changed_subsystems() -> None:
    store = SystemStateStore(SystemState())

    await store.update_subsystem("hardware", HardwareState())

    change = await store.wait_for_change_notice(0, timeout=0.01)

    assert change.version == 1
    assert change.changed_subsystems == frozenset({"hardware"})
    assert change.events_changed is False


async def test_store_wait_for_change_notice_reports_event_updates() -> None:
    store = SystemStateStore(SystemState())

    await store.append_event(EventEntry(source="tests", title="event created"))

    change = await store.wait_for_change_notice(0, timeout=0.01)

    assert change.version == 1
    assert change.changed_subsystems == frozenset()
    assert change.events_changed is True
