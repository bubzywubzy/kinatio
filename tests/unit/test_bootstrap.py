from kinatio.config import AppConfig
from kinatio.domain.models import (
    AuditFinding,
    AuditState,
    CollectionAccessInfo,
    CollectorHealth,
    LogEntry,
    LogsState,
    SecurityFinding,
    SecurityState,
    SystemState,
)
from kinatio.runtime.bootstrap import (
    build_collectors,
    create_runtime_services,
    prime_runtime_store,
    redact_privileged_state,
    state_for_persistence,
)


def test_build_collectors_applies_configured_intervals() -> None:
    config = AppConfig(refresh_intervals={"hardware": 42.0, "logs": 7.5})

    collectors = build_collectors(config)
    by_subsystem = {collector.subsystem: collector for collector in collectors}

    assert by_subsystem["hardware"].interval == 42.0
    assert by_subsystem["logs"].interval == 7.5


def test_create_runtime_services_wires_shared_dependencies() -> None:
    services = create_runtime_services()

    assert services.auth.runner is services.runner
    assert services.scheduler.store is services.store
    assert [collector.subsystem for collector in services.scheduler.collectors] == [
        collector.subsystem for collector in services.collectors
    ]
    assert not hasattr(services, "executor")
    assert not hasattr(services, "registry")
    assert not hasattr(services, "policy")
    assert not hasattr(services, "planner")
    assert not hasattr(services, "audit")


def test_create_runtime_services_excludes_removed_control_plane_helpers() -> None:
    services = create_runtime_services()

    assert services.__dataclass_fields__.keys() == {
        "auth",
        "cache",
        "collectors",
        "config",
        "runner",
        "scheduler",
        "store",
    }


def test_redact_privileged_state_clears_cached_privileged_subsystems() -> None:
    state = SystemState(
        logs=LogsState(
            entries=[LogEntry(message="cached privileged log line")],
            live_enabled=True,
            collection_access=CollectionAccessInfo(requires_auth=True, elevated=True, detail="Collected through sudo."),
        ),
        security=SecurityState(
            sudo_available=True,
            sudo_authenticated=True,
            sudo_non_interactive=True,
            sudo_configured=True,
            sudo_summary="sudo already unlocked",
            users=["alice"],
            findings=[SecurityFinding(severity="critical", title="cached finding", detail="secret")],
            collection_access=CollectionAccessInfo(requires_auth=True, elevated=True, detail="Collected through sudo."),
        ),
        audit=AuditState(
            audit_status="enabled 1",
            findings=[AuditFinding(severity="warning", title="cached audit", detail="secret")],
            collection_access=CollectionAccessInfo(requires_auth=True, elevated=True, detail="Collected through sudo."),
        ),
        collector_health={
            "logs": CollectorHealth(collector="logs", status="ok", last_completed_status="ok"),
            "security": CollectorHealth(collector="security", status="ok", last_completed_status="ok"),
            "audit": CollectorHealth(collector="audit", status="ok", last_completed_status="ok"),
        },
    )

    redacted = redact_privileged_state(state)

    assert redacted.logs.entries == []
    assert redacted.logs.live_enabled is False
    assert redacted.logs.availability.available is False
    assert redacted.security.users == []
    assert redacted.security.findings == []
    assert redacted.audit.findings == []
    assert redacted.collector_health["logs"].availability.dependency == "sudo"
    assert redacted.hardware == state.hardware


def test_state_for_persistence_redacts_privileged_subsystems() -> None:
    state = SystemState(
        logs=LogsState(entries=[LogEntry(message="cached privileged log line")], live_enabled=True),
        security=SecurityState(
            sudo_available=True,
            sudo_authenticated=True,
            users=["alice"],
            findings=[SecurityFinding(severity="critical", title="cached finding", detail="secret")],
            sudo_summary="sudo unlocked",
        ),
        audit=AuditState(
            audit_status="enabled 1",
            findings=[AuditFinding(severity="warning", title="cached audit", detail="secret")],
        ),
    )

    persisted = state_for_persistence(state)

    assert persisted.logs.entries == []
    assert persisted.logs.live_enabled is False
    assert persisted.security.users == []
    assert persisted.audit.findings == []


async def test_prime_runtime_store_redacts_cached_privileged_state_before_restore(monkeypatch) -> None:
    services = create_runtime_services()
    services.cache.load = lambda: SystemState(
        logs=LogsState(entries=[LogEntry(message="cached privileged log line")], live_enabled=True),
        security=SecurityState(
            sudo_available=True,
            sudo_authenticated=True,
            users=["alice"],
            findings=[SecurityFinding(severity="critical", title="cached finding", detail="secret")],
            sudo_summary="sudo unlocked",
        ),
        audit=AuditState(
            audit_status="enabled 1",
            findings=[AuditFinding(severity="warning", title="cached audit", detail="secret")],
        ),
    )

    async def fake_refresh_runtime_context(_services) -> None:
        return None

    monkeypatch.setattr("kinatio.runtime.bootstrap.refresh_runtime_context", fake_refresh_runtime_context)

    await prime_runtime_store(services)
    _, state = await services.store.snapshot()

    assert state.logs.entries == []
    assert state.logs.live_enabled is False
    assert state.security.users == []
    assert state.audit.findings == []
