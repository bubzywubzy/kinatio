import asyncio
from time import monotonic

import pytest
from rich.console import Console
from textual.css.query import NoMatches
from textual.widget import MountError
from textual.widgets import DataTable, ListView, Static

from kinatio.app import KinatioApp
from kinatio.config import AppConfig
from kinatio.domain.models import AuditFinding, AuditState, HardwareState, LogEntry, LogsState, NetworkAddress, NetworkInterface, NetworkState, PackageEntry, PackagesState, ProcessEntry, ProcessesState, SecurityFinding, SecurityState, ServiceEntry, ServicesState, SystemState
from kinatio.execution.auth import SudoAuthState
from kinatio.ui.sections import DetailViewState, InteractiveSectionView, build_interactive_table_spec, is_interactive_section


class StubAuth:
    def __init__(self, state: SudoAuthState) -> None:
        self.state = state
        self.refresh_calls = 0

    async def refresh(self) -> SudoAuthState:
        self.refresh_calls += 1
        return self.state


class StubScheduler:
    def __init__(self) -> None:
        self.calls: list[str | None] = []
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1

    async def refresh_now(self, subsystem: str | None = None) -> None:
        self.calls.append(subsystem)


class CollectorStub:
    def __init__(self, subsystem: str) -> None:
        self.subsystem = subsystem


class StubCache:
    def __init__(self) -> None:
        self.saved_states: list[SystemState] = []

    def load(self):
        return None

    def save(self, state: SystemState) -> None:
        self.saved_states.append(state.model_copy(deep=True))


class FocusSpy:
    def __init__(self) -> None:
        self.focus_calls = 0

    def focus(self) -> None:
        self.focus_calls += 1


def _render_plain_text(renderable: object) -> str:
    console = Console(width=140)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_subsystem_for_section_reads_shared_policy_metadata() -> None:
    app = KinatioApp()

    assert app._subsystem_for_section("Audit") == "audit"
    assert app._subsystem_for_section("Kernel") == "os_state"
    assert app._subsystem_for_section("Overview") is None


def test_overview_payload_signature_tracks_package_changes() -> None:
    app = KinatioApp()
    baseline = SystemState()
    updated = baseline.model_copy(deep=True)
    updated.packages = PackagesState(
        manager="pacman",
        installed_count=10,
        update_count=2,
        entries=[PackageEntry(name="bash", version="5.2", update_version="5.3")],
    )

    assert app._section_payload_signature("Overview", baseline) != app._section_payload_signature("Overview", updated)


def test_collection_gate_defers_only_policy_managed_subsystems() -> None:
    app = KinatioApp()
    app.auth_state = SudoAuthState.locked("still locked")

    logs_gate = app._collection_gate(CollectorStub("logs"))
    network_gate = app._collection_gate(CollectorStub("network"))

    assert logs_gate is not None
    assert logs_gate.dependency == "sudo"
    assert network_gate is None


def test_detail_stack_resets_to_process_interaction_defaults() -> None:
    app = KinatioApp()

    app._reset_detail_stack("Processes")
    view = app._current_view()

    assert view.section == "Processes"
    assert view.mode == "list"
    assert view.sort_key == "cpu"
    assert view.sort_desc is True


def test_detail_stack_reset_aligns_parent_category_with_leaf_section() -> None:
    app = KinatioApp()

    app._reset_detail_stack("Processes")

    assert app.selected_category == "Operations"
    assert app.selected_section == "Processes"


def test_detail_stack_canonicalizes_legacy_network_and_security_sections_for_tui() -> None:
    app = KinatioApp()

    app._reset_detail_stack("Network")
    assert app.selected_category == "Network"
    assert app.selected_section == "Network Summary"

    app._reset_detail_stack("Security")
    assert app.selected_category == "Security"
    assert app.selected_section == "Security Posture"


def test_side_panel_labels_are_single_line_and_compact() -> None:
    app = KinatioApp()

    category_label = app._category_label("Operations", selected=False)
    section_label = app._section_label("Logs", selected=False)

    assert "\n" not in category_label.plain
    assert category_label.plain == "Operations"
    assert "\n" not in section_label.plain
    assert section_label.plain == "Logs"
    assert "Recent logs and live follow support" not in section_label.plain


def test_brand_context_hint_guides_locked_privileged_views() -> None:
    app = KinatioApp()
    app.auth_state = SudoAuthState.locked("still locked")

    app._reset_detail_stack("Logs")

    hint = app._brand_context_hint().lower()

    assert "deferred" in hint
    assert "unlock sudo" in hint


def test_brand_context_hint_surfaces_logs_follow_and_noise_controls() -> None:
    app = KinatioApp()
    app.auth_state = SudoAuthState.authenticated_state()

    app._reset_detail_stack("Logs")

    hint = app._brand_context_hint().lower()

    assert "logs list ready" in hint
    assert "pause" in hint
    assert "show noise" in hint


def test_locked_side_panel_labels_hide_privileged_badges() -> None:
    app = KinatioApp()
    app.auth_state = SudoAuthState.locked("still locked")

    section_label = app._section_label("Logs", selected=False)

    assert "sudo" not in section_label.plain.lower()
    assert "live" not in section_label.plain.lower()


def test_detail_stack_respects_log_noise_default_from_config() -> None:
    app = KinatioApp(AppConfig(suppress_known_log_noise_by_default=False))

    app._reset_detail_stack("Logs")

    assert app._current_view().show_log_noise is True


def test_detail_focus_only_available_for_interactive_root_lists() -> None:
    app = KinatioApp()
    app.selected_section = "Processes"
    app._reset_detail_stack("Processes")

    assert is_interactive_section(app.selected_section) is True
    assert app._detail_focus_available() is True

    app._detail_stack.append(DetailViewState(section="Processes", mode="detail", target="1234"))

    assert app._detail_focus_available() is False


def test_sync_focus_retries_when_interactive_view_is_temporarily_unavailable(monkeypatch) -> None:
    app = KinatioApp()
    app.selected_section = "Processes"
    app._reset_detail_stack("Processes")
    app.focused_pane = "detail"

    sidebar = FocusSpy()
    scheduled: list[object] = []

    def fake_query_one(selector, *args, **kwargs):
        del args, kwargs
        if selector == InteractiveSectionView:
            raise NoMatches("interactive detail view not ready")
        if selector == "#sidebar":
            return sidebar
        raise AssertionError(f"unexpected selector {selector!r}")

    monkeypatch.setattr(app, "query_one", fake_query_one)
    monkeypatch.setattr(
        app,
        "call_after_refresh",
        lambda callback, *args, **kwargs: scheduled.append(callback) or True,
    )

    app._sync_focus()

    assert app.focused_pane == "detail"
    assert sidebar.focus_calls == 0
    assert len(scheduled) == 1


async def test_refresh_from_store_restores_detail_focus_after_rebuild() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "processes",
        ProcessesState(
            total_processes=2,
            entries=[
                ProcessEntry(pid=100, name="python", username="alice", cpu_percent=61.0, memory_percent=12.0),
                ProcessEntry(pid=200, name="ssh", username="root", cpu_percent=7.0, memory_percent=1.5),
            ],
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Processes"
        app._reset_detail_stack("Processes")
        app.focused_pane = "detail"

        await app._refresh_from_store(force=True)
        await pilot.pause()

        detail_view = app.query_one(InteractiveSectionView)
        table = app.query_one("#interactive-table", DataTable)

        assert app.focused_pane == "detail"
        assert detail_view.current_key() == "100"
        assert table.has_focus is True


async def test_refresh_from_store_keeps_interactive_widget_mounted_for_unrelated_updates() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "processes",
        ProcessesState(
            total_processes=2,
            entries=[
                ProcessEntry(pid=100, name="python", username="alice", cpu_percent=61.0, memory_percent=12.0),
                ProcessEntry(pid=200, name="ssh", username="root", cpu_percent=7.0, memory_percent=1.5),
            ],
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Processes"
        app._reset_detail_stack("Processes")
        app.focused_pane = "detail"

        await app._refresh_from_store(force=True)
        await pilot.pause()

        detail_view = app.query_one(InteractiveSectionView)

        await app.store.update_subsystem("hardware", HardwareState())
        await app._refresh_from_store(force=True)
        await pilot.pause()

        assert app.query_one(InteractiveSectionView) is detail_view
        assert detail_view.current_key() == "100"


async def test_refresh_from_store_updates_interactive_widget_in_place_and_preserves_selection() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "processes",
        ProcessesState(
            total_processes=2,
            entries=[
                ProcessEntry(pid=100, name="python", username="alice", cpu_percent=61.0, memory_percent=12.0),
                ProcessEntry(pid=200, name="ssh", username="root", cpu_percent=7.0, memory_percent=1.5),
            ],
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Processes"
        app._reset_detail_stack("Processes")
        app.focused_pane = "detail"

        await app._refresh_from_store(force=True)
        await pilot.pause()

        detail_view = app.query_one(InteractiveSectionView)
        app._current_view().cursor_key = "200"

        await app.store.update_subsystem(
            "processes",
            ProcessesState(
                total_processes=2,
                entries=[
                    ProcessEntry(pid=100, name="python", username="alice", cpu_percent=22.0, memory_percent=10.0),
                    ProcessEntry(pid=200, name="ssh", username="root", cpu_percent=19.0, memory_percent=1.5),
                ],
            ),
        )
        await app._refresh_from_store(force=True)
        await pilot.pause()

        assert app.query_one(InteractiveSectionView) is detail_view
        assert detail_view.current_key() == "200"


async def test_background_refresh_skips_interactive_spec_rebuild_for_unrelated_changes(monkeypatch) -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "processes",
        ProcessesState(
            total_processes=2,
            entries=[
                ProcessEntry(pid=100, name="python", username="alice", cpu_percent=61.0, memory_percent=12.0),
                ProcessEntry(pid=200, name="ssh", username="root", cpu_percent=7.0, memory_percent=1.5),
            ],
        ),
    )

    build_calls = 0

    def spy_build_interactive_table_spec(state, view, *, log_noise_patterns=None):
        nonlocal build_calls
        build_calls += 1
        return build_interactive_table_spec(state, view, log_noise_patterns=log_noise_patterns)

    monkeypatch.setattr("kinatio.app.build_interactive_table_spec", spy_build_interactive_table_spec)

    async with app.run_test() as pilot:
        app.selected_section = "Processes"
        app._reset_detail_stack("Processes")
        app.focused_pane = "detail"

        await app._refresh_from_store(force=True)
        await pilot.pause()

        initial_calls = build_calls
        observed_version = app._observed_version

        await app.store.update_subsystem("hardware", HardwareState())
        store_change = await app.store.wait_for_change_notice(observed_version, timeout=0.1)
        await app._refresh_from_store(force=True, refresh_reason="background", store_change=store_change)
        await pilot.pause()

        assert build_calls == initial_calls


async def test_background_refresh_keeps_screen_still_and_uses_notification(monkeypatch) -> None:
    app = KinatioApp(AppConfig(interactive_auto_refresh_min_interval=0.0))
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "processes",
        ProcessesState(
            total_processes=2,
            entries=[
                ProcessEntry(pid=100, name="python", username="alice", cpu_percent=61.0, memory_percent=12.0),
                ProcessEntry(pid=200, name="ssh", username="root", cpu_percent=7.0, memory_percent=1.5),
            ],
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Processes"
        app._reset_detail_stack("Processes")
        app.focused_pane = "detail"

        await app._refresh_from_store(force=True)
        await pilot.pause()

        detail_view = app.query_one(InteractiveSectionView)
        app._current_view().live_updates_enabled = True
        app._current_view().cursor_key = "200"

        focus_resyncs: list[str] = []
        notifications: list[str] = []
        monkeypatch.setattr(app, "_schedule_focus_sync", lambda: focus_resyncs.append("called"))
        monkeypatch.setattr(app, "notify", lambda message: notifications.append(message))

        await app.store.update_subsystem(
            "processes",
            ProcessesState(
                total_processes=2,
                entries=[
                    ProcessEntry(pid=100, name="python", username="alice", cpu_percent=23.0, memory_percent=10.0),
                    ProcessEntry(pid=200, name="ssh", username="root", cpu_percent=19.0, memory_percent=1.5),
                ],
            ),
        )
        await app._refresh_from_store(force=True, refresh_reason="background")
        await pilot.pause()

        assert app.query_one(InteractiveSectionView) is detail_view
        assert detail_view.current_key() == "200"
        assert focus_resyncs == []
        assert notifications == ["Processes refreshed"]


async def test_manual_refresh_notifies_even_when_visible_content_is_unchanged(monkeypatch) -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]

    notifications: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message: notifications.append(message))

    async with app.run_test() as pilot:
        app.selected_section = "Overview"
        await app._refresh_from_store(force=True, refresh_reason="manual")
        await pilot.pause()

    assert notifications == ["Overview refreshed"]


async def test_background_refresh_defers_interactive_updates_when_live_updates_are_paused(monkeypatch) -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    notifications: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message: notifications.append(message))

    await app.store.update_subsystem(
        "processes",
        ProcessesState(
            total_processes=2,
            entries=[
                ProcessEntry(pid=100, name="python", username="alice", cpu_percent=61.0, memory_percent=12.0),
                ProcessEntry(pid=200, name="ssh", username="root", cpu_percent=7.0, memory_percent=1.5),
            ],
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Processes"
        app._reset_detail_stack("Processes")
        await app._refresh_from_store(force=True)
        await pilot.pause()

        app._current_view().live_updates_enabled = False

        detail_view = app.query_one(InteractiveSectionView)
        original_signature = app._detail_signature

        await app.store.update_subsystem(
            "processes",
            ProcessesState(
                total_processes=2,
                entries=[
                    ProcessEntry(pid=100, name="python", username="alice", cpu_percent=23.0, memory_percent=10.0),
                    ProcessEntry(pid=200, name="ssh", username="root", cpu_percent=19.0, memory_percent=1.5),
                ],
            ),
        )
        await app._refresh_from_store(force=True, refresh_reason="background")
        await pilot.pause()

        assert app.query_one(InteractiveSectionView) is detail_view
        assert app._detail_signature == original_signature
        assert notifications == ["Processes updated in background"]


async def test_toggle_live_updates_applies_pending_background_changes(monkeypatch) -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    monkeypatch.setattr(app, "notify", lambda message: None)

    await app.store.update_subsystem(
        "processes",
        ProcessesState(
            total_processes=1,
            entries=[ProcessEntry(pid=100, name="python", username="alice", cpu_percent=61.0, memory_percent=12.0)],
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Processes"
        app._reset_detail_stack("Processes")
        await app._refresh_from_store(force=True)
        await pilot.pause()

        app._current_view().live_updates_enabled = False

        await app.store.update_subsystem(
            "processes",
            ProcessesState(
                total_processes=1,
                entries=[ProcessEntry(pid=200, name="ssh", username="root", cpu_percent=19.0, memory_percent=1.5)],
            ),
        )
        await app._refresh_from_store(force=True, refresh_reason="background")
        await pilot.pause()

        assert app.query_one(InteractiveSectionView).current_key() == "100"

        await app.action_toggle_live_updates()
        await pilot.pause()

        assert app._current_view().live_updates_enabled is True
        assert app.query_one(InteractiveSectionView).current_key() == "200"


async def test_toggle_live_updates_from_detail_view_updates_root_list_state(monkeypatch) -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    monkeypatch.setattr(app, "notify", lambda message: None)

    await app.store.update_subsystem(
        "processes",
        ProcessesState(
            total_processes=1,
            entries=[ProcessEntry(pid=100, name="python", username="alice", cpu_percent=61.0, memory_percent=12.0)],
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Processes"
        app._reset_detail_stack("Processes")
        await app._refresh_from_store(force=True)
        await pilot.pause()

        await app.action_open_selected_item()
        await pilot.pause()

        assert app._detail_stack[0].live_updates_enabled is True

        await app.action_toggle_live_updates()
        await pilot.pause()

        assert app._detail_stack[0].live_updates_enabled is False
        assert app._detail_stack[-1].live_updates_enabled is False


async def test_toggle_log_noise_reveals_hidden_environment_log_entries(monkeypatch) -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    notifications: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message: notifications.append(message))

    await app.store.update_subsystem(
        "logs",
        LogsState(
            entries=[
                LogEntry(
                    source="kwin",
                    unit="kwin_wayland",
                    priority="warning",
                    message="window::os::wayland::pointer > set_cursor: Unable to set cursor to hand: cursor not found",
                ),
                LogEntry(
                    source="journal",
                    unit="sshd.service",
                    priority="info",
                    message="Accepted publickey for alice",
                ),
            ]
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Logs"
        app._reset_detail_stack("Logs")

        await app._refresh_from_store(force=True)
        await pilot.pause()

        detail_view = app.query_one(InteractiveSectionView)

        assert len(detail_view.spec.rows) == 1
        assert app._current_view().show_log_noise is False

        await app.action_toggle_log_noise()
        await pilot.pause()

        assert len(detail_view.spec.rows) == 2
        assert app._current_view().show_log_noise is True
        assert notifications == ["Known environment log noise shown"]


async def test_poll_selected_section_auth_state_skips_refresh_until_poll_interval_elapses() -> None:
    app = KinatioApp(AppConfig(auth_refresh_interval=0.0, privileged_auth_poll_interval=30.0))
    app.selected_section = "Logs"
    app.auth = StubAuth(SudoAuthState.locked("still locked"))  # type: ignore[assignment]
    app._last_auth_refresh = monotonic()

    changed = await app._poll_selected_section_auth_state()

    assert changed is False
    assert app.auth.refresh_calls == 0


async def test_refresh_auth_state_redacts_cached_privileged_subsystems_when_locked() -> None:
    app = KinatioApp(AppConfig(auth_refresh_interval=0.0))
    await app.store.update_subsystem(
        "logs",
        LogsState(entries=[LogEntry(message="cached privileged log line")], live_enabled=True),
    )
    await app.store.update_subsystem(
        "security",
        SecurityState(
            sudo_available=True,
            sudo_authenticated=True,
            users=["alice"],
            findings=[SecurityFinding(severity="critical", title="cached finding", detail="secret")],
            sudo_summary="sudo unlocked",
        ),
    )
    await app.store.update_subsystem(
        "audit",
        AuditState(
            audit_status="enabled 1",
            findings=[AuditFinding(severity="warning", title="cached audit", detail="secret")],
        ),
    )
    app.auth = StubAuth(SudoAuthState.locked("still locked"))  # type: ignore[assignment]

    await app._refresh_auth_state(force=True)
    _, state = await app.store.snapshot()

    assert state.logs.entries == []
    assert state.logs.live_enabled is False
    assert state.security.users == []
    assert state.security.findings == []
    assert state.audit.findings == []


async def test_on_unmount_saves_redacted_cache_snapshot_after_authenticated_privileged_session() -> None:
    app = KinatioApp(AppConfig(auth_refresh_interval=0.0))
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "logs",
        LogsState(entries=[LogEntry(message="cached privileged log line")], live_enabled=True),
    )
    await app.store.update_subsystem(
        "security",
        SecurityState(
            sudo_available=True,
            sudo_authenticated=True,
            users=["alice"],
            findings=[SecurityFinding(severity="critical", title="cached finding", detail="secret")],
            sudo_summary="sudo unlocked",
        ),
    )
    await app.store.update_subsystem(
        "audit",
        AuditState(
            audit_status="enabled 1",
            findings=[AuditFinding(severity="warning", title="cached audit", detail="secret")],
        ),
    )

    async with app.run_test() as pilot:
        await pilot.pause()

    assert app.cache.saved_states
    saved_state = app.cache.saved_states[-1]
    assert saved_state.logs.entries == []
    assert saved_state.logs.live_enabled is False
    assert saved_state.security.users == []
    assert saved_state.audit.findings == []


async def test_poll_selected_section_auth_state_refreshes_deferred_subsystem_when_auth_changes() -> None:
    app = KinatioApp(AppConfig(auth_refresh_interval=0.0, privileged_auth_poll_interval=0.0))
    app.selected_section = "Logs"
    app.auth_state = SudoAuthState.locked("still locked")
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]

    changed = await app._poll_selected_section_auth_state()

    assert changed is True
    assert app.auth.refresh_calls == 1
    assert app.scheduler.calls == ["logs"]


def test_wayland_pointer_shape_escape_sequences_are_suppressed() -> None:
    app = KinatioApp()

    class DriverSpy:
        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, data: str) -> None:
            self.writes.append(data)

    driver = DriverSpy()
    app._driver = driver  # type: ignore[assignment]

    app._set_pointer_shape("pointer")
    app._set_pointer_shape("text")
    app._set_pointer_shape("default")

    assert driver.writes == []


async def test_refresh_from_store_handles_duplicate_service_names_without_duplicate_keys() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "services",
        ServicesState(
            services=[
                ServiceEntry(
                    name="dup.service",
                    active_state="active",
                    sub_state="running",
                    description="first",
                    unit_file_state="enabled",
                    is_enabled=True,
                ),
                ServiceEntry(
                    name="dup.service",
                    active_state="failed",
                    sub_state="dead",
                    description="second",
                    unit_file_state="enabled",
                    is_enabled=True,
                ),
            ]
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Services"
        app._reset_detail_stack("Services")
        app.focused_pane = "detail"

        await app._refresh_from_store(force=True)
        await pilot.pause()

        detail_view = app.query_one(InteractiveSectionView)
        table = app.query_one("#interactive-table", DataTable)

        assert [row_key.value for row_key in table.rows.keys()] == ["dup.service", "dup.service-1"]

        table.move_cursor(row=1, column=0, scroll=False)
        await pilot.pause()

        assert detail_view.current_target() == "dup.service"


async def test_refresh_from_store_rebuilds_interactive_table_columns_when_switching_sections() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "logs",
        LogsState(
            entries=[
                LogEntry(
                    source="journal",
                    unit="sshd.service",
                    priority="info",
                    message="Accepted publickey for alice",
                )
            ]
        ),
    )
    await app.store.update_subsystem(
        "network",
        NetworkState(
            interfaces=[
                NetworkInterface(
                    name="eth0",
                    is_up=True,
                    addresses=[NetworkAddress(family="inet", address="192.168.1.20")],
                    rx_bytes=1024,
                    tx_bytes=2048,
                    speed_mbps=1000,
                )
            ]
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Logs"
        app._reset_detail_stack("Logs")
        app.focused_pane = "detail"

        await app._refresh_from_store(force=True)
        await pilot.pause()

        detail_view = app.query_one(InteractiveSectionView)
        table = app.query_one("#interactive-table", DataTable)

        assert detail_view.spec.columns == ("Time", "Priority", "Unit", "Message")
        assert len(table.columns) == 4

        app.selected_section = "Interfaces"
        app._reset_detail_stack("Interfaces")

        await app._refresh_from_store(force=True)
        await pilot.pause()

        assert app.query_one(InteractiveSectionView) is detail_view
        assert detail_view.spec.columns == ("Interface", "State", "Address", "RX", "TX", "Speed")
        assert len(table.columns) == 6
        assert detail_view.current_key() == "eth0"


async def test_activate_category_replaces_interactive_detail_with_static_content() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "processes",
        ProcessesState(
            total_processes=1,
            entries=[
                ProcessEntry(pid=100, name="python", username="alice", cpu_percent=61.0, memory_percent=12.0),
            ],
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Processes"
        app._reset_detail_stack("Processes")
        app.focused_pane = "detail"

        await app._refresh_from_store(force=True)
        await pilot.pause()

        assert app._detail_kind == "interactive"
        assert app.query_one(InteractiveSectionView) is not None

        await app._activate_category("Overview")
        await pilot.pause()

        assert app.selected_category == "Overview"
        assert app.selected_section == "Overview"
        assert app.focused_pane == "sidebar"
        assert app._detail_kind == "static"
        detail_content = app.query_one("#detail-content", Static)
        assert detail_content is not None
        assert detail_content.parent is not None and detail_content.parent.id == "detail-static-stage"
        try:
            app.query_one(InteractiveSectionView)
        except NoMatches:
            pass
        else:
            raise AssertionError("interactive detail should be replaced after switching to a static category")


async def test_refresh_from_store_rebuilds_sidebar_for_selected_parent_category() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]

    async with app.run_test() as pilot:
        app._reset_detail_stack("Processes")

        await app._refresh_from_store(force=True)
        await pilot.pause()

        sidebar = app.query_one("#sidebar", ListView)

        assert app.selected_category == "Operations"
        assert [item.name for item in sidebar.children if getattr(item, "name", None)] == [
            "Processes",
            "Services",
            "Containers",
            "Sessions",
            "Events",
        ]


def test_contextual_bindings_change_for_locked_and_logs_list_states() -> None:
    app = KinatioApp()
    app.auth_state = SudoAuthState.locked("still locked")
    app.selected_section = "Security Posture"
    app.focused_pane = "sidebar"

    locked_bindings = app._contextual_bindings()

    assert locked_bindings == (
        ("↑↓", "sections"),
        ("Tab", "focus"),
        ("U", "unlock"),
        ("R", "refresh"),
        ("Q", "quit"),
    )

    app.auth_state = SudoAuthState.authenticated_state()
    app._reset_detail_stack("Logs")
    app.selected_section = "Logs"
    app.focused_pane = "detail"

    logs_bindings = app._contextual_bindings()

    assert logs_bindings == (
        ("↑↓", "move"),
        ("Enter", "open"),
        ("/", "filter"),
        ("S", "sort"),
        ("Tab", "next"),
        ("F", "pause"),
        ("N", "show noise"),
        ("V", "live on"),
        ("Q", "quit"),
    )


def test_contextual_bindings_surface_live_toggle_outside_detail_list_for_interactive_sections() -> None:
    app = KinatioApp()

    app._reset_detail_stack("Processes")
    app.focused_pane = "categories"
    assert ("V", "live on") in app._contextual_bindings()

    app.focused_pane = "sidebar"
    assert ("V", "live on") in app._contextual_bindings()

    app._detail_stack.append(
        DetailViewState(
            section="Processes",
            mode="detail",
            target="100",
            live_updates_enabled=True,
        )
    )
    app.focused_pane = "detail"
    assert ("V", "live on") in app._contextual_bindings()


async def test_keybind_bar_updates_when_switching_between_list_and_detail_modes() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "processes",
        ProcessesState(
            total_processes=1,
            entries=[ProcessEntry(pid=100, name="python", username="alice", cpu_percent=61.0, memory_percent=12.0)],
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Processes"
        app._reset_detail_stack("Processes")
        app.focused_pane = "detail"

        await app._refresh_from_store(force=True)
        await pilot.pause()

        assert app._keybind_signature == (
            ("↑↓", "move"),
            ("Enter", "open"),
            ("/", "filter"),
            ("S", "sort"),
            ("Tab", "next"),
            ("V", "live on"),
            ("Q", "quit"),
        )

        with pytest.raises(NoMatches):
            app.query_one("#keybinds", Static)

        await app.action_open_selected_item()
        await pilot.pause()

        assert app._keybind_signature == (
            ("Esc", "back"),
            ("V", "live on"),
            ("Q", "quit"),
        )


async def test_keybind_bar_mounts_below_main_layout_so_navigation_panes_keep_their_width() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]

    async with app.run_test() as pilot:
        await pilot.pause()

        root_children = list(app.screen.children)
        brand_strip = app.query_one("#brand-strip", Static)

        with pytest.raises(NoMatches):
            app.query_one("#keybinds", Static)
        with pytest.raises(NoMatches):
            app.query_one("#status", Static)
        assert root_children[0] is brand_strip


async def test_launch_starts_in_quiet_startup_mode_with_categories_only() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]

    async with app.run_test() as pilot:
        await pilot.pause()

        sidebar = app.query_one("#sidebar", ListView)
        detail_banner = app.query_one("#detail-banner", Static)
        detail = app.query_one("#detail-content", Static)
        brand_strip = app.query_one("#brand-strip", Static)
        shell_center = app.query_one("#shell-center")

        assert app.startup_mode is True
        assert app.focused_pane == "categories"
        assert sidebar.display is False
        assert detail_banner.display is False
        assert app._detail_kind == "static"
        assert app._detail_signature == ("startup", "Overview", app.auth_state.status)
        assert app._brand_signature is not None
        assert app._brand_signature[0] == "startup-ascii"
        assert brand_strip is not None
        assert shell_center is not None
        assert detail.parent is not None and detail.parent.id == "detail-static-stage"

        with pytest.raises(NoMatches):
            app.query_one("#status", Static)


async def test_selecting_current_category_exits_startup_mode_and_reveals_sections() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]

    async with app.run_test() as pilot:
        await pilot.pause()

        await app._handle_navigation_selection("categories", "Overview", activation="selected")
        await pilot.pause()

        sidebar = app.query_one("#sidebar", ListView)
        detail_banner = app.query_one("#detail-banner", Static)

        assert app.startup_mode is False
        assert sidebar.display is True
        assert detail_banner.display is True
        assert app._detail_kind == "static"
        assert app._detail_signature is not None
        assert app._detail_signature[:2] == ("static", "Overview")


async def test_brand_strip_mounts_outside_main_layout_and_above_status() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]

    async with app.run_test() as pilot:
        await pilot.pause()

        main_layout = app.query_one("#main-layout")
        shell_center = app.query_one("#shell-center")
        brand_strip = app.query_one("#brand-strip", Static)
        root_children = list(app.screen.children)

        assert brand_strip.parent is not main_layout
        assert main_layout.parent is shell_center
        assert root_children.index(brand_strip) < root_children.index(shell_center)


async def test_interactive_sections_start_with_live_updates_enabled_for_seamless_refreshes() -> None:
    app = KinatioApp()

    app._reset_detail_stack("Processes")
    assert app._current_view().live_updates_enabled is True

    app._reset_detail_stack("Services")
    assert app._current_view().live_updates_enabled is True

    app._reset_detail_stack("Interfaces")
    assert app._current_view().live_updates_enabled is True

    app._reset_detail_stack("Packages")
    assert app._current_view().live_updates_enabled is True


async def test_refresh_from_store_renders_packages_as_interactive_list() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "packages",
        PackagesState(
            manager="pacman",
            installed_count=2,
            update_count=1,
            entries=[
                PackageEntry(name="bash", version="5.2", update_version="5.3"),
                PackageEntry(name="vim", version="9.1.1"),
            ],
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Packages"
        app._reset_detail_stack("Packages")
        app.focused_pane = "detail"

        await app._refresh_from_store(force=True)
        await pilot.pause()

        detail_view = app.query_one(InteractiveSectionView)

        assert app._detail_kind == "interactive"
        assert detail_view.spec.title == "Packages"
        assert detail_view.current_key() == "bash"


async def test_open_selected_item_mounts_drill_in_inside_centered_static_stage() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]
    await app.store.update_subsystem(
        "processes",
        ProcessesState(
            total_processes=1,
            entries=[
                ProcessEntry(pid=100, name="python", username="alice", cpu_percent=61.0, memory_percent=12.0),
            ],
        ),
    )

    async with app.run_test() as pilot:
        app.selected_section = "Processes"
        app._reset_detail_stack("Processes")
        app.focused_pane = "detail"

        await app._refresh_from_store(force=True)
        await pilot.pause()

        await app.action_open_selected_item()
        await pilot.pause()

        detail_content = app.query_one("#detail-content", Static)

        assert app._detail_kind == "static"
        assert app._detail_signature is not None
        assert app._detail_signature[:3] == ("static", "Processes", "detail")
        assert detail_content.parent is not None and detail_content.parent.id == "detail-static-stage"
        with pytest.raises(NoMatches):
            app.query_one(InteractiveSectionView)


async def test_rebuild_section_list_noops_until_sidebar_is_mounted(monkeypatch) -> None:
    app = KinatioApp()

    class SidebarStub:
        is_mounted = False

        async def remove_children(self) -> None:
            raise AssertionError("remove_children should not run before the sidebar is mounted")

        async def mount(self, widget) -> None:
            del widget
            raise AssertionError("mount should not run before the sidebar is mounted")

    monkeypatch.setattr(
        app,
        "query_one",
        lambda selector, *args, **kwargs: SidebarStub() if selector == "#sidebar" else (_ for _ in ()).throw(AssertionError(selector)),
    )

    assert await app._rebuild_section_list() is False


async def test_rebuild_section_list_swallows_mount_race_when_sidebar_unmounts_mid_rebuild(monkeypatch) -> None:
    app = KinatioApp()
    sidebar = None

    class SidebarStub:
        def __init__(self) -> None:
            self.is_mounted = True

        async def remove_children(self) -> None:
            return None

        async def mount(self, widget) -> None:
            del widget
            self.is_mounted = False
            raise MountError("Can't mount widget(s) before ListView(id='sidebar') is mounted")

    sidebar = SidebarStub()
    monkeypatch.setattr(
        app,
        "query_one",
        lambda selector, *args, **kwargs: sidebar if selector == "#sidebar" else (_ for _ in ()).throw(AssertionError(selector)),
    )

    assert await app._rebuild_section_list() is False


async def test_navigation_selection_serializes_category_clicks(monkeypatch) -> None:
    app = KinatioApp()
    release = asyncio.Event()
    first_entered = asyncio.Event()
    seen: list[str] = []
    concurrent_activations = 0
    max_concurrent_activations = 0

    async def fake_activate_category(category: str) -> None:
        nonlocal concurrent_activations, max_concurrent_activations
        seen.append(category)
        concurrent_activations += 1
        max_concurrent_activations = max(max_concurrent_activations, concurrent_activations)
        if category == "Network":
            first_entered.set()
        await release.wait()
        concurrent_activations -= 1

    monkeypatch.setattr(app, "_activate_category", fake_activate_category)

    first = asyncio.create_task(app._handle_navigation_selection("categories", "Network"))
    await first_entered.wait()

    second = asyncio.create_task(app._handle_navigation_selection("categories", "Security"))
    await asyncio.sleep(0)

    assert max_concurrent_activations == 1

    release.set()
    await asyncio.gather(first, second)

    assert seen == ["Network", "Security"]


async def test_refresh_from_store_uses_split_network_subcategories() -> None:
    app = KinatioApp()
    app.auth = StubAuth(SudoAuthState.authenticated_state())  # type: ignore[assignment]
    app.scheduler = StubScheduler()  # type: ignore[assignment]
    app.cache = StubCache()  # type: ignore[assignment]

    async with app.run_test() as pilot:
        app._reset_detail_stack("Network Summary")

        await app._refresh_from_store(force=True)
        await pilot.pause()

        sidebar = app.query_one("#sidebar", ListView)

        assert app.selected_category == "Network"
        assert [item.name for item in sidebar.children if getattr(item, "name", None)] == [
            "Network Summary",
            "Interfaces",
            "Routes & DNS",
            "Ports & Connections",
            "Firewall",
        ]