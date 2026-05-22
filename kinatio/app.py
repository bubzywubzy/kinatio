"""Top-level Textual application."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

from rich.align import Align
from rich.text import Text
from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding
from textual.containers import Center, CenterMiddle, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import MountError
from textual.widgets import DataTable, Label, ListItem, ListView, Static

from kinatio.config import DEFAULT_CONFIG, AppConfig
from kinatio.domain.models import AvailabilityInfo, CollectorHealth, SystemState
from kinatio.sections import (
    DEFERRED_SUBSYSTEMS,
    TOP_LEVEL_CATEGORIES,
    get_category_sections,
    get_default_section,
    get_section_category,
    get_section_policy,
    get_tui_visible_section,
    section_payload_signature,
)
from kinatio.runtime.bootstrap import (
    create_runtime_services,
    prime_runtime_store,
    redact_locked_privileged_state,
    refresh_runtime_context,
    state_for_persistence,
)
from kinatio.runtime.store import StoreChange
from kinatio.ui.layout import (
    format_brand_header,
    format_contextual_keybinds,
    format_locked_section,
    format_section_health_banner,
    format_startup_welcome,
    format_state_section,
)
from kinatio.ui.modals import SearchModal, SudoPasswordModal
from kinatio.ui.sections import DetailViewState, InteractiveSectionView, build_interactive_table_spec, cycle_sort, default_view_state, interactive_spec_signature, is_interactive_section, render_interactive_detail


class KinatioApp(App[None]):
    """Main Textual shell for the Kinatio control center."""

    TITLE = "Kinatio"
    SUB_TITLE = "Linux System Control Deck"
    CSS = """
    Screen {
        background: #0b0d10;
        color: #d7dbde;
    }

    #brand-strip {
        background: #0f1216;
        color: #c8d0d7;
        height: auto;
        padding: 1 2 0 2;
        border-top: solid #2a3138;
        border-bottom: solid #2a3138;
    }

    Button,
    Button:hover,
    Button:disabled,
    Button:disabled:hover {
        pointer: default;
    }

    #main-layout {
        width: 100%;
        max-width: 148;
        height: 1fr;
        padding: 0 1 1 1;
    }

    #shell-center {
        height: 1fr;
    }

    #categories {
        width: 22;
        border: round #30363d;
        background: #101317;
        padding: 0;
        margin-right: 1;
    }

    #categories:focus {
        border: round #7a1b1b;
    }

    #sidebar {
        width: 22;
        border: round #30363d;
        background: #101317;
        padding: 0;
        margin-right: 1;
    }

    #sidebar:focus {
        border: round #7a1b1b;
    }

    #detail {
        border: round #2a3138;
        background: #0d1013;
        padding: 1 2;
        overflow-y: auto;
    }

    #detail-banner {
        color: #b7bec5;
        margin-bottom: 1;
        width: 100%;
    }

    #detail-content-host {
        height: 1fr;
        width: 100%;
    }

    #detail-static-stage {
        width: 100%;
        height: 1fr;
    }

    .detail-static-surface {
        width: auto;
        max-width: 96;
    }

    #textual-toastrack {
        dock: top;
        align: right top;
        margin-top: 1;
        margin-bottom: 0;
    }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("n", "toggle_log_noise", "Noise"),
        Binding("u", "unlock_section", "Unlock"),
        Binding("tab", "toggle_focus", "Focus"),
        Binding("enter", "open_selected_item", "Open"),
        Binding("escape", "navigate_back", "Back"),
        Binding("/", "search_detail", "Search"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("v", "toggle_live_updates", "Live"),
    ]

    selected_category = reactive("Overview")
    selected_section = reactive("Overview")
    focused_pane = reactive("categories")
    startup_mode = reactive(False)

    def __init__(self, config: AppConfig | None = None) -> None:
        super().__init__()
        self.config = config or DEFAULT_CONFIG
        runtime = create_runtime_services(self.config, collection_gate=self._collection_gate)
        self.runtime = runtime
        self.store = runtime.store
        self.cache = runtime.cache
        self.runner = runtime.runner
        self.auth = runtime.auth
        self.auth_state = runtime.auth.state
        self.collectors = runtime.collectors
        self.scheduler = runtime.scheduler
        self._scheduler_started = False
        self._ui_task: asyncio.Task[None] | None = None
        self._observed_version = -1
        self._last_auth_refresh = 0.0
        self._detail_stack: list[DetailViewState] = [self._default_view_state(self.selected_section)]
        self._refresh_lock = asyncio.Lock()
        self._navigation_lock = asyncio.Lock()
        self._sidebar_rebuild_lock = asyncio.Lock()
        self._focus_sync_pending = False
        self._navigation_sync_in_progress = False
        self._selected_section_by_category = {
            category: get_default_section(category) or category
            for category in TOP_LEVEL_CATEGORIES
        }
        self._sidebar_sections_snapshot = tuple(get_category_sections(self.selected_category))
        self._detail_kind = "static"
        self._detail_signature: tuple[Any, ...] | None = None
        self._brand_signature: tuple[Any, ...] | None = None
        self._status_signature: tuple[Any, ...] | None = None
        self._keybind_signature: tuple[tuple[str, str], ...] | None = None
        self._last_refresh_notification_at = 0.0
        self._last_refresh_notification_section: str | None = None
        self._last_detail_apply_at: dict[str, float] = {}
        self._pending_background_refresh_sections: set[str] = set()
        self._last_hostname = "host n/a"
        self._last_alert_count = 0
        self._collector_names_by_subsystem = {
            collector.subsystem: collector.name for collector in self.collectors
        }

    def _set_pointer_shape(self, shape: str) -> None:
        """Suppress terminal pointer-shape escape sequences for compatibility.

        Textual uses the Kitty pointer-shape protocol to request cursor shapes such as
        ``pointer`` and ``text``. Some Wayland terminal setups log warnings when those
        cursor names can't be resolved by the compositor theme. This TUI is primarily
        keyboard-driven, so disabling pointer-shape emission entirely is the most
        reliable way to avoid noisy terminal warnings without affecting navigation.
        """
        del shape

    def _sync_runtime_service_refs(self) -> None:
        """Keep the shared runtime bundle aligned with app-level service overrides."""

        self.runtime.config = self.config
        self.runtime.store = self.store
        self.runtime.cache = self.cache
        self.runtime.runner = self.runner
        self.runtime.auth = self.auth
        self.runtime.collectors = self.collectors
        self.runtime.scheduler = self.scheduler

    def compose(self) -> ComposeResult:
        yield Static("", id="brand-strip")
        with Center(id="shell-center"):
            with Horizontal(id="main-layout"):
                with ListView(id="categories"):
                    for category in TOP_LEVEL_CATEGORIES:
                        yield ListItem(Label(self._category_label(category, selected=category == self.selected_category)), name=category)
                with ListView(id="sidebar"):
                    for section in get_category_sections(self.selected_category):
                        yield ListItem(Label(self._section_label(section, selected=section == self.selected_section)), name=section)
                with Vertical(id="detail"):
                    yield Static("", id="detail-banner")
                    with Vertical(id="detail-content-host"):
                        with CenterMiddle(id="detail-static-stage"):
                            yield Static(
                                "Kinatio is initializing.",
                                id="detail-content",
                                classes="detail-static-surface",
                            )

    async def on_mount(self) -> None:
        self._sync_runtime_service_refs()
        await prime_runtime_store(self.runtime)
        await self._refresh_auth_state(force=True)
        await self.scheduler.start()
        self._scheduler_started = True
        self._ui_task = asyncio.create_task(self._observe_state())
        category_list = self.query_one("#categories", ListView)
        category_list.index = TOP_LEVEL_CATEGORIES.index(self.selected_category)
        list_view = self.query_one("#sidebar", ListView)
        list_view.index = 0
        self._sidebar_sections_snapshot = tuple(get_category_sections(self.selected_category))
        self._sync_category_labels()
        self._sync_sidebar_labels()
        self._set_startup_mode(True)
        await self._refresh_from_store(force=True)
        self._refresh_keybind_bar()
        self._schedule_focus_sync()

    async def on_unmount(self) -> None:
        if self._ui_task is not None:
            self._ui_task.cancel()
            await asyncio.gather(self._ui_task, return_exceptions=True)
        if self._scheduler_started:
            await self.scheduler.stop()
        self._sync_runtime_service_refs()
        _, state = await self.store.snapshot()
        self.cache.save(state_for_persistence(state))

    async def action_refresh_now(self) -> None:
        await self.scheduler.refresh_now()
        await self._refresh_from_store(force=True, refresh_reason="manual")

    async def action_unlock_section(self) -> None:
        if not self._section_requires_auth(self.selected_section):
            return
        await self._refresh_auth_state(force=True)
        if not self._section_is_locked(self.selected_section):
            await self._refresh_from_store(force=True)
            return
        self.push_screen(
            SudoPasswordModal(self.selected_section, self.auth_state.message),
            callback=self._handle_unlock_result,
        )

    async def action_toggle_focus(self) -> None:
        if self.startup_mode:
            self.focused_pane = "categories"
            self._sync_focus()
            self._sync_navigation_labels()
            self._refresh_brand_strip()
            self._refresh_keybind_bar()
            return

        panes = ["categories", "sidebar"]
        if self._detail_focus_available():
            panes.append("detail")
        current = self.focused_pane if self.focused_pane in panes else panes[0]
        self.focused_pane = panes[(panes.index(current) + 1) % len(panes)]
        self._sync_focus()
        self._sync_navigation_labels()
        self._refresh_brand_strip()
        self._refresh_keybind_bar()

    async def action_open_selected_item(self) -> None:
        view = self._current_view()
        if view.mode != "list" or not is_interactive_section(self.selected_section):
            return
        target = self._selected_detail_target()
        if target is None:
            return
        if self.selected_section == "Logs" and view.follow_enabled:
            view.follow_enabled = False
        self._detail_stack.append(
            DetailViewState(
                section=self.selected_section,
                mode="detail",
                target=target,
                cursor_key=target,
                search_query=view.search_query,
                sort_key=view.sort_key,
                sort_desc=view.sort_desc,
                follow_enabled=view.follow_enabled,
                live_updates_enabled=view.live_updates_enabled,
                show_log_noise=view.show_log_noise,
            )
        )
        self.focused_pane = "sidebar"
        await self._refresh_from_store(force=True)

    async def action_navigate_back(self) -> None:
        if len(self._detail_stack) <= 1:
            return
        self._detail_stack.pop()
        if self._detail_focus_available():
            self.focused_pane = "detail"
        await self._refresh_from_store(force=True)

    async def action_search_detail(self) -> None:
        view = self._current_view()
        if view.mode != "list" or not is_interactive_section(self.selected_section):
            return
        self.push_screen(
            SearchModal(self.selected_section, current_query=view.search_query),
            callback=self._handle_search_result,
        )

    async def action_cycle_sort(self) -> None:
        view = self._current_view()
        if view.mode != "list" or not is_interactive_section(self.selected_section):
            return
        view.sort_key, view.sort_desc = cycle_sort(self.selected_section, view.sort_key, view.sort_desc)
        if self.selected_section == "Logs":
            view.follow_enabled = False
        view.cursor_key = None
        await self._refresh_from_store(force=True)

    async def action_toggle_follow(self) -> None:
        view = self._current_view()
        if self.selected_section != "Logs" or view.mode != "list":
            return
        view.follow_enabled = not view.follow_enabled
        if view.follow_enabled:
            view.sort_key = "timestamp"
            view.sort_desc = True
            view.cursor_key = None
        await self._refresh_from_store(force=True)

    async def action_toggle_live_updates(self) -> None:
        live_view = self._live_toggle_view()
        if live_view is None:
            return
        enabled = not live_view.live_updates_enabled
        self._set_live_updates_enabled(enabled)
        if enabled:
            self._pending_background_refresh_sections.discard(self.selected_section)
            await self._refresh_from_store(force=True, refresh_reason="manual")
            self.notify(f"{self.selected_section} live updates enabled")
            return
        self.notify(f"{self.selected_section} live updates paused")
        await self._refresh_from_store(force=True)

    async def action_toggle_log_noise(self) -> None:
        view = self._current_view()
        if self.selected_section != "Logs" or view.mode != "list":
            return
        view.show_log_noise = not view.show_log_noise
        view.cursor_key = None
        await self._refresh_from_store(force=True)
        self.notify(
            "Known environment log noise shown"
            if view.show_log_noise
            else "Known environment log noise hidden"
        )

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        await self._handle_navigation_selection(
            event.list_view.id,
            event.item.name if event.item else None,
            activation="highlight",
        )

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        await self._handle_navigation_selection(
            event.list_view.id,
            event.item.name if event.item else None,
            activation="selected",
        )

    async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "interactive-table":
            return
        view = self._current_view()
        if view.mode == "list":
            view.cursor_key = event.row_key.value

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "interactive-table":
            return
        view = self._current_view()
        if view.mode == "list":
            view.cursor_key = event.row_key.value
        await self.action_open_selected_item()

    async def _handle_navigation_selection(
        self,
        list_id: str | None,
        item_name: str | None,
        *,
        activation: str = "highlight",
    ) -> None:
        if self._navigation_sync_in_progress:
            return
        if not item_name:
            return
        async with self._navigation_lock:
            if list_id == "categories":
                if self.startup_mode and activation == "selected" and item_name == self.selected_category:
                    self._set_startup_mode(False)
                    await self._refresh_from_store(force=True)
                    return
                await self._activate_category(item_name)
                return
            if list_id == "sidebar":
                await self._activate_section(item_name)

    def _mounted_list_view(self, selector: str) -> ListView | None:
        try:
            list_view = self.query_one(selector, ListView)
        except (NoMatches, ScreenStackError):
            return None
        if not list_view.is_mounted:
            return None
        return list_view

    def _mounted_static(self, selector: str) -> Static | None:
        try:
            widget = self.query_one(selector, Static)
        except (NoMatches, ScreenStackError):
            return None
        if not widget.is_mounted:
            return None
        return widget

    def _reset_visual_signatures(self) -> None:
        self._detail_signature = None
        self._brand_signature = None
        self._status_signature = None
        self._keybind_signature = None

    def _apply_startup_visibility(self) -> None:
        sidebar = self._mounted_list_view("#sidebar")
        if sidebar is not None:
            sidebar.display = not self.startup_mode

        detail_banner = self._mounted_static("#detail-banner")
        if detail_banner is not None:
            detail_banner.display = not self.startup_mode

    def _set_startup_mode(self, enabled: bool) -> None:
        if self.startup_mode == enabled:
            return
        self.startup_mode = enabled
        self._reset_visual_signatures()
        self._apply_startup_visibility()

    async def _activate_category(self, category: str) -> None:
        if category == self.selected_category:
            return
        sections = get_category_sections(category)
        if not sections:
            return

        self.selected_category = category
        remembered_section = self._selected_section_by_category.get(category)
        self.selected_section = remembered_section if remembered_section in sections else sections[0]
        self._selected_section_by_category[category] = self.selected_section
        self._reset_detail_stack(self.selected_section)
        if self.focused_pane == "detail" and not self._detail_focus_available():
            self.focused_pane = "sidebar"
        await self._rebuild_section_list()
        self._sync_category_labels()
        await self._refresh_from_store(force=True)

    async def _activate_section(self, section: str) -> None:
        section = self._canonical_tui_section(section)
        if section == self.selected_section:
            return
        self.selected_section = section
        category = get_section_category(section)
        if category is not None:
            self._selected_section_by_category[category] = section
        self._reset_detail_stack(self.selected_section)
        if self.focused_pane == "detail" and not self._detail_focus_available():
            self.focused_pane = "sidebar"
        self._sync_sidebar_labels()
        await self._refresh_from_store(force=True)

    async def _rebuild_section_list(self) -> bool:
        async with self._sidebar_rebuild_lock:
            sections = get_category_sections(self.selected_category)
            self._sidebar_sections_snapshot = tuple(sections)
            list_view = self._mounted_list_view("#sidebar")
            if list_view is None:
                return False

            self._navigation_sync_in_progress = True
            try:
                if not list_view.is_mounted:
                    return False
                await list_view.remove_children()
                if not list_view.is_mounted:
                    return False
                for section in sections:
                    if not list_view.is_mounted:
                        return False
                    await list_view.mount(
                        ListItem(
                            Label(self._section_label(section, selected=section == self.selected_section)),
                            name=section,
                        )
                    )
                if sections and list_view.is_mounted:
                    list_view.index = sections.index(self.selected_section) if self.selected_section in sections else 0
            except MountError:
                return False
            finally:
                self._navigation_sync_in_progress = False

        return True

    def _sync_navigation_indexes(self) -> None:
        category_list = self._mounted_list_view("#categories")
        sidebar_list = self._mounted_list_view("#sidebar")
        if category_list is None and sidebar_list is None:
            return

        self._navigation_sync_in_progress = True
        try:
            if category_list is not None and self.selected_category in TOP_LEVEL_CATEGORIES:
                category_list.index = TOP_LEVEL_CATEGORIES.index(self.selected_category)
            sections = get_category_sections(self.selected_category)
            if sidebar_list is not None and sections:
                sidebar_list.index = sections.index(self.selected_section) if self.selected_section in sections else 0
        finally:
            self._navigation_sync_in_progress = False

    def _category_label(self, category: str, *, selected: bool) -> Text:
        title_style = "bold white" if selected else "grey70"
        return Text(category, style=title_style, justify="left")

    def _section_label(self, section: str, *, selected: bool) -> Text:
        title_style = "bold white" if selected else "grey62"
        return Text(section, style=title_style, justify="left")

    def _compute_alert_count(self, state: SystemState) -> int:
        error_count = sum(
            1
            for health in state.collector_health.values()
            if health.status == "error"
            or (health.status == "running" and health.last_completed_status == "error")
            or (
                not health.availability.available
                and not (
                    health.status == "idle"
                    and (health.availability.reason or "").lower().startswith("collection deferred")
                )
            )
        )
        critical_findings = sum(1 for finding in state.security.findings if finding.severity == "critical")
        failed_services = sum(1 for service in state.services.services if service.is_failed)
        return error_count + critical_findings + failed_services

    def _section_requires_auth(self, section: str) -> bool:
        policy = get_section_policy(section)
        return bool(policy and policy.requires_auth)

    def _section_is_locked(self, section: str) -> bool:
        return self._section_requires_auth(section) and not self.auth_state.authenticated

    async def _authenticate_session(self, password: str | None) -> bool:
        if password is None:
            return False
        self.auth_state = await self.auth.authenticate(password)
        self._last_auth_refresh = monotonic()
        await redact_locked_privileged_state(self.store, self.auth_state)
        self._sync_navigation_labels()
        return self.auth_state.authenticated

    async def _handle_unlock_result(self, password: str | None) -> None:
        if not await self._authenticate_session(password):
            return
        if self.auth_state.authenticated:
            subsystem = self._subsystem_for_section(self.selected_section)
            if subsystem in DEFERRED_SUBSYSTEMS:
                await self.scheduler.refresh_now(subsystem=subsystem)
        await self._refresh_from_store(force=True)

    def _subsystem_for_section(self, section: str) -> str | None:
        policy = get_section_policy(section)
        return policy.subsystem if policy is not None else None

    def _collection_gate(self, collector: object) -> AvailabilityInfo | None:
        subsystem = getattr(collector, "subsystem", None)
        if subsystem in DEFERRED_SUBSYSTEMS and not self.auth_state.authenticated:
            return AvailabilityInfo(
                available=False,
                reason="Collection deferred until sudo authentication is unlocked.",
                dependency="sudo",
            )
        return None

    async def _refresh_auth_state(self, *, force: bool = False) -> None:
        now = monotonic()
        if force or (now - self._last_auth_refresh) >= self.config.auth_refresh_interval:
            self.auth_state = await self.auth.refresh()
            self._last_auth_refresh = now
            await redact_locked_privileged_state(self.store, self.auth_state)
            self._sync_navigation_labels()

    async def _poll_selected_section_auth_state(self) -> bool:
        if not self._section_requires_auth(self.selected_section):
            return False
        if (monotonic() - self._last_auth_refresh) < self.config.privileged_auth_poll_interval:
            return False

        previous_state = self.auth_state
        await self._refresh_auth_state()
        if self.auth_state == previous_state:
            return False

        if self.auth_state.authenticated:
            subsystem = self._subsystem_for_section(self.selected_section)
            if subsystem in DEFERRED_SUBSYSTEMS:
                await self.scheduler.refresh_now(subsystem=subsystem)
        return True

    async def _refresh_runtime_context(self) -> None:
        self._sync_runtime_service_refs()
        await refresh_runtime_context(self.runtime)

    async def _handle_search_result(self, query: str | None) -> None:
        if query is None:
            return
        view = self._current_view()
        if view.mode != "list":
            return
        view.search_query = query.strip()
        if self.selected_section == "Logs" and view.search_query:
            view.follow_enabled = False
        view.cursor_key = None
        await self._refresh_from_store(force=True)

    def _default_view_state(self, section: str) -> DetailViewState:
        return default_view_state(
            section,
            show_log_noise=section == "Logs" and not self.config.suppress_known_log_noise_by_default,
        )

    def _auth_display(self) -> tuple[str, str]:
        if self.auth_state.status == "authenticated":
            return "authenticated", "bold white"
        if self.auth_state.status == "locked":
            return "locked", "bold red"
        return "unavailable", "grey62"

    def _sync_category_labels(self) -> None:
        list_view = self._mounted_list_view("#categories")
        if list_view is None:
            return
        for item in list_view.children:
            if isinstance(item, ListItem) and item.name:
                item.query_one(Label).update(
                    self._category_label(item.name, selected=item.name == self.selected_category)
                )

    def _sync_navigation_labels(self) -> None:
        try:
            self._sync_navigation_indexes()
            self._sync_category_labels()
            self._sync_sidebar_labels()
        except (NoMatches, ScreenStackError):
            return

    def _sync_sidebar_labels(self) -> None:
        list_view = self._mounted_list_view("#sidebar")
        if list_view is None:
            return
        for item in list_view.children:
            if isinstance(item, ListItem) and item.name:
                item.query_one(Label).update(self._section_label(item.name, selected=item.name == self.selected_section))

    def _reset_detail_stack(self, section: str) -> None:
        if self.startup_mode:
            self._set_startup_mode(False)
        section = self._canonical_tui_section(section)
        category = get_section_category(section)
        if category is not None:
            self.selected_category = category
            self._selected_section_by_category[category] = section
            self.selected_section = section
        self._detail_stack = [self._default_view_state(section)]

    def _canonical_tui_section(self, section: str) -> str:
        canonical = get_tui_visible_section(section)
        category = get_section_category(canonical)
        if category is None:
            return canonical
        remembered = self._selected_section_by_category.get(category)
        sections = get_category_sections(category)
        if canonical in sections:
            return canonical
        if remembered in sections:
            return remembered
        return sections[0] if sections else canonical

    def _current_view(self) -> DetailViewState:
        if not self._detail_stack:
            self._reset_detail_stack(self.selected_section)
        return self._detail_stack[-1]

    def _live_toggle_view(self) -> DetailViewState | None:
        if not is_interactive_section(self.selected_section):
            return None
        if not self._detail_stack:
            self._reset_detail_stack(self.selected_section)
        root_view = self._detail_stack[0]
        if root_view.section != self.selected_section or root_view.mode != "list":
            return None
        return root_view

    def _set_live_updates_enabled(self, enabled: bool) -> None:
        for view in self._detail_stack:
            if view.section == self.selected_section:
                view.live_updates_enabled = enabled

    def _live_toggle_binding(self) -> tuple[str, str] | None:
        live_view = self._live_toggle_view()
        if live_view is None:
            return None
        return ("V", f"live {'on' if live_view.live_updates_enabled else 'off'}")

    def _detail_focus_available(self) -> bool:
        view = self._current_view()
        return is_interactive_section(self.selected_section) and view.mode == "list"

    def _sync_focus(self) -> None:
        if self.startup_mode:
            category_list = self._mounted_list_view("#categories")
            if category_list is None:
                self._schedule_focus_sync()
                return
            category_list.focus()
            self.focused_pane = "categories"
            return

        if self.focused_pane == "categories":
            category_list = self._mounted_list_view("#categories")
            if category_list is None:
                self._schedule_focus_sync()
                return
            category_list.focus()
            return
        if self.focused_pane != "detail" or not self._detail_focus_available():
            sidebar_list = self._mounted_list_view("#sidebar")
            if sidebar_list is None:
                self._schedule_focus_sync()
                return
            sidebar_list.focus()
            self.focused_pane = "sidebar"
            return
        try:
            detail_view = self.query_one(InteractiveSectionView)
        except NoMatches:
            self._schedule_focus_sync()
            return
        detail_view.focus_default()

    def _schedule_focus_sync(self) -> None:
        if self._focus_sync_pending:
            return

        self._focus_sync_pending = True

        def _run_focus_sync() -> None:
            self._focus_sync_pending = False
            self._sync_focus()

        self.call_after_refresh(_run_focus_sync)

    def _selected_detail_target(self) -> str | None:
        view = self._current_view()
        if view.mode != "list":
            return view.target
        try:
            detail_view = self.query_one(InteractiveSectionView)
        except NoMatches:
            return view.cursor_key
        return detail_view.current_target() or detail_view.resolve_target(view.cursor_key) or view.cursor_key

    def _interaction_hint(self) -> str:
        return " · ".join(f"{key} {label}" for key, label in self._contextual_bindings())

    def _brand_context_hint(self) -> str:
        if self.startup_mode:
            return "Choose a category to begin · Enter opens sections · R refresh"

        live_binding = self._live_toggle_binding()
        if self._section_is_locked(self.selected_section):
            return "privileged collection deferred · U unlock sudo · R refresh when ready"

        view = self._current_view()
        if view.mode == "detail":
            hints = ["detail open", "Esc back"]
            if live_binding is not None:
                hints.append(f"{live_binding[0]} {live_binding[1]}")
            return " · ".join(hints)

        if self.selected_section == "Logs" and view.mode == "list":
            hints = [
                "logs list ready",
                "/ filter",
                f"F {'pause' if view.follow_enabled else 'follow newest'}",
                f"N {'hide' if view.show_log_noise else 'show'} noise",
            ]
            if live_binding is not None:
                hints.append(f"{live_binding[0]} {live_binding[1]}")
            return " · ".join(hints)

        if is_interactive_section(self.selected_section):
            hints = ["interactive list ready", "Enter detail", "/ filter", "S sort"]
            if live_binding is not None:
                hints.append(f"{live_binding[0]} {live_binding[1]}")
            return " · ".join(hints)

        if self.focused_pane == "categories":
            return "browse categories with ↑↓ · Tab to sections · R refresh"
        return "browse sections with ↑↓ · Tab focus · R refresh"

    def _contextual_bindings(self) -> tuple[tuple[str, str], ...]:
        if self.startup_mode:
            return (
                ("↑↓", "categories"),
                ("Enter", "browse"),
                ("R", "refresh"),
                ("Q", "quit"),
            )

        live_binding = self._live_toggle_binding()
        if self._section_is_locked(self.selected_section):
            if self.focused_pane == "categories":
                return (
                    ("↑↓", "categories"),
                    ("Tab", "next"),
                    ("U", "unlock"),
                    ("R", "refresh"),
                    ("Q", "quit"),
                )
            return (
                ("↑↓", "sections"),
                ("Tab", "focus"),
                ("U", "unlock"),
                ("R", "refresh"),
                ("Q", "quit"),
            )

        view = self._current_view()
        if not is_interactive_section(self.selected_section):
            if self.focused_pane == "categories":
                return (
                    ("↑↓", "categories"),
                    ("Tab", "next"),
                    ("R", "refresh"),
                    ("Q", "quit"),
                )
            return (
                ("↑↓", "sections"),
                ("Tab", "focus"),
                ("R", "refresh"),
                ("Q", "quit"),
            )

        if self.focused_pane == "categories":
            bindings = [
                ("↑↓", "categories"),
                ("Tab", "next"),
            ]
            if live_binding is not None:
                bindings.append(live_binding)
            bindings.extend([
                ("R", "refresh"),
                ("Q", "quit"),
            ])
            return tuple(bindings)

        if self.focused_pane == "sidebar" and view.mode == "list":
            bindings = [
                ("↑↓", "subviews"),
                ("Enter", "select"),
                ("Tab", "next"),
            ]
            if live_binding is not None:
                bindings.append(live_binding)
            bindings.extend([
                ("R", "refresh"),
                ("Q", "quit"),
            ])
            return tuple(bindings)

        if view.mode == "detail":
            bindings: list[tuple[str, str]] = [("Esc", "back")]
            if live_binding is not None:
                bindings.append(live_binding)
            bindings.append(("Q", "quit"))
            return tuple(bindings)

        bindings: list[tuple[str, str]] = [
            ("↑↓", "move"),
            ("Enter", "open"),
            ("/", "filter"),
            ("S", "sort"),
            ("Tab", "next"),
        ]
        if self.selected_section == "Logs":
            bindings.append(("F", "pause" if view.follow_enabled else "follow newest"))
            bindings.append(("N", "hide noise" if view.show_log_noise else "show noise"))
        if live_binding is not None:
            bindings.append(live_binding)
        bindings.append(("Q", "quit"))
        return tuple(bindings)

    def _refresh_keybind_bar(self) -> None:
        try:
            keybind_widget = self.query_one("#keybinds", Static)
        except (NoMatches, ScreenStackError):
            self._keybind_signature = self._contextual_bindings()
            return
        bindings = self._contextual_bindings()
        if bindings == self._keybind_signature:
            return
        self._keybind_signature = bindings
        keybind_widget.update(format_contextual_keybinds(bindings))

    def _refresh_brand_strip(self) -> None:
        try:
            brand_widget = self.query_one("#brand-strip", Static)
        except (NoMatches, ScreenStackError):
            return
        auth_label, auth_style = self._auth_display()
        context_hint = self._brand_context_hint()
        width = self.size.width or 0
        show_ascii_brand = self.config.show_ascii_header and width >= self.config.ascii_header_min_width
        brand_mode = (
            ("startup-ascii" if show_ascii_brand else "startup-compact")
            if self.startup_mode
            else ("ascii" if show_ascii_brand else "compact")
        )
        signature = (
            brand_mode,
            self.selected_category,
            self.selected_section,
            self.focused_pane,
            auth_label,
            self._last_hostname,
            self._last_alert_count,
            context_hint,
        )
        if signature == self._brand_signature:
            return
        self._brand_signature = signature
        brand_widget.update(
            format_brand_header(
                width=width,
                selected_category=self.selected_category,
                selected_section=self.selected_section,
                auth_label=auth_label,
                auth_style=auth_style,
                context_hint=context_hint,
                hostname=self._last_hostname,
                alert_count=self._last_alert_count,
                show_ascii=self.config.show_ascii_header,
                ascii_min_width=self.config.ascii_header_min_width,
                compact=self.startup_mode,
                focus_label="categories" if self.startup_mode else None,
            )
        )

    def _should_defer_detail_refresh(self, *, refresh_reason: str) -> bool:
        if refresh_reason != "background":
            return False
        view = self._current_view()
        if view.mode != "list" or not is_interactive_section(self.selected_section):
            return False
        if not view.live_updates_enabled:
            return True
        if self.selected_section != "Logs":
            return False
        if view.follow_enabled:
            return False
        last_applied_at = self._last_detail_apply_at.get(self.selected_section, 0.0)
        return (monotonic() - last_applied_at) < self.config.interactive_auto_refresh_min_interval

    def _detail_relevant_subsystems(self, section: str) -> frozenset[str]:
        policy = get_section_policy(section)
        if policy is None:
            return frozenset()
        subsystems = policy.updated_at_subsystems or policy.payload_subsystems
        if not subsystems and policy.subsystem is not None:
            subsystems = (policy.subsystem,)
        return frozenset(subsystems)

    def _store_change_affects_detail(self, store_change: StoreChange) -> bool:
        if self.startup_mode:
            return False

        if self._section_is_locked(self.selected_section):
            return False

        policy = get_section_policy(self.selected_section)
        if policy is None:
            return True
        if policy.payload_mode == "events":
            return store_change.events_changed

        relevant_subsystems = self._detail_relevant_subsystems(self.selected_section)
        if not relevant_subsystems:
            return True
        return bool(relevant_subsystems.intersection(store_change.changed_subsystems))

    def _content_signature(self, state: SystemState, view: DetailViewState) -> tuple[Any, ...]:
        if self.startup_mode:
            del state, view
            return ("startup", self.selected_category, self.auth_state.status)

        if self._section_is_locked(self.selected_section):
            return ("locked", self.selected_section, self.auth_state.status, self.auth_state.message)

        if view.mode == "list":
            interactive_spec = build_interactive_table_spec(
                state,
                view,
                log_noise_patterns=self.config.log_noise_patterns,
            )
            if interactive_spec is not None:
                return ("interactive", self.selected_section, *interactive_spec_signature(interactive_spec, selected_key=view.cursor_key))

        return (
            "static",
            self.selected_section,
            view.mode,
            view.target,
            self._section_payload_signature(self.selected_section, state),
        )

    def _section_payload_signature(self, section: str, state: SystemState) -> str:
        return section_payload_signature(section, state)

    async def _render_detail_content(self, state: SystemState) -> bool:
        view = self._current_view()
        content_signature = self._content_signature(state, view)
        if content_signature == self._detail_signature:
            return False

        if self.startup_mode:
            await self._set_static_detail_content(
                format_startup_welcome(selected_category=self.selected_category, state=state),
                signature=content_signature,
            )
            return True

        if self._section_is_locked(self.selected_section):
            await self._set_static_detail_content(
                format_locked_section(self.selected_section, self.auth_state.status, self.auth_state.message),
                signature=content_signature,
            )
            return True

        interactive_spec = build_interactive_table_spec(
            state,
            view,
            log_noise_patterns=self.config.log_noise_patterns,
        )
        if interactive_spec is not None:
            await self._set_interactive_detail_content(
                interactive_spec,
                selected_key=view.cursor_key,
                signature=content_signature,
            )
            return True

        renderable = render_interactive_detail(
            state,
            view,
            log_noise_patterns=self.config.log_noise_patterns,
        ) or format_state_section(self.selected_section, state)
        await self._set_static_detail_content(renderable, signature=content_signature)
        return True

    async def _set_static_detail_content(self, renderable: object, *, signature: tuple[Any, ...]) -> None:
        content_host = self.query_one("#detail-content-host", Vertical)
        if self._detail_kind != "static":
            await content_host.remove_children()
            stage = CenterMiddle(id="detail-static-stage")
            await content_host.mount(stage)
            await stage.mount(
                Static(renderable, id="detail-content", classes="detail-static-surface")
            )  # type: ignore[arg-type]
            self._detail_kind = "static"
        else:
            self.query_one("#detail-content", Static).update(renderable)  # type: ignore
        self._detail_signature = signature

    async def _set_interactive_detail_content(
        self,
        spec: Any,
        *,
        selected_key: str | None,
        signature: tuple[Any, ...],
    ) -> None:
        content_host = self.query_one("#detail-content-host", Vertical)
        if self._detail_kind != "interactive":
            await content_host.remove_children()
            await content_host.mount(InteractiveSectionView(spec, selected_key=selected_key))
            self._detail_kind = "interactive"
        else:
            self.query_one(InteractiveSectionView).update_spec(spec, selected_key=selected_key)
        self._detail_signature = signature

    def _status_signature_for(
        self,
        state: SystemState,
        *,
        auth_label: str,
        auth_style: str,
        interaction_hint: str,
    ) -> tuple[Any, ...]:
        health_values = tuple(
            sorted(
                (
                    name,
                    health.status,
                    health.last_completed_status,
                    health.error,
                    health.availability.available,
                    health.availability.reason,
                    health.last_finished_at.isoformat() if health.last_finished_at else None,
                )
                for name, health in state.collector_health.items()
            )
        )
        return (
            self.selected_category,
            self.selected_section,
            auth_label,
            auth_style,
            interaction_hint,
            self._section_payload_signature(self.selected_section, state),
            health_values,
            len(state.events),
        )

    def _section_health(self, section: str, state: SystemState) -> CollectorHealth | None:
        subsystem = self._subsystem_for_section(section)
        if subsystem is None:
            return None
        collector_name = self._collector_names_by_subsystem.get(subsystem, subsystem)
        return state.collector_health.get(collector_name)

    async def _observe_state(self) -> None:
        while True:
            try:
                store_change = await self.store.wait_for_change_notice(
                    self._observed_version,
                    self.config.ui_refresh_interval,
                )
            except asyncio.CancelledError:
                return
            if store_change.version != self._observed_version:
                await self._refresh_from_store(
                    force=True,
                    refresh_reason="background",
                    store_change=store_change,
                )
            elif await self._poll_selected_section_auth_state():
                await self._refresh_from_store(force=True, refresh_reason="background")

    def _maybe_notify_refresh(self, *, refresh_reason: str, detail_changed: bool) -> None:
        if self.startup_mode and refresh_reason != "manual":
            return

        if refresh_reason not in {"background", "manual"}:
            return
        if refresh_reason == "background" and not detail_changed and self.selected_section not in self._pending_background_refresh_sections:
            return

        now = monotonic()
        cooldown = max(self.config.ui_refresh_interval * 4, 6.0)
        if (
            refresh_reason == "background"
            and self._last_refresh_notification_section == self.selected_section
            and (now - self._last_refresh_notification_at) < cooldown
        ):
            return

        self._last_refresh_notification_section = self.selected_section
        self._last_refresh_notification_at = now
        message = f"{self.selected_section} refreshed"
        if refresh_reason == "background" and self.selected_section in self._pending_background_refresh_sections:
            message = f"{self.selected_section} updated in background"
        self.notify(message)

    async def _refresh_from_store(
        self,
        force: bool = False,
        *,
        refresh_reason: str = "view",
        store_change: StoreChange | None = None,
    ) -> None:
        async with self._refresh_lock:
            version, state = await self.store.snapshot()
            if not force and version == self._observed_version:
                return
            if store_change is not None and store_change.version != version:
                store_change = None
            self._observed_version = version
            self._last_hostname = state.os_state.hostname or "host n/a"
            self._last_alert_count = self._compute_alert_count(state)
            canonical_section = self._canonical_tui_section(self.selected_section)
            if canonical_section != self.selected_section:
                self._reset_detail_stack(canonical_section)
            if tuple(get_category_sections(self.selected_category)) != self._sidebar_sections_snapshot:
                await self._rebuild_section_list()
            self._apply_startup_visibility()
            self._sync_navigation_labels()
            previous_detail_kind = self._detail_kind
            previous_detail_signature = self._detail_signature
            banner_renderable = None
            if not self.startup_mode and not self._section_is_locked(self.selected_section):
                banner_renderable = format_section_health_banner(
                    self.selected_section,
                    self._section_health(self.selected_section, state),
                )
            auth_label, auth_style = self._auth_display()
            banner_widget = self.query_one("#detail-banner", Static)
            banner_widget.update(Align.center(banner_renderable) if banner_renderable is not None else "")
            self._refresh_brand_strip()

            detail_changed = False
            detail_change_relevant = store_change is None or self._store_change_affects_detail(store_change)
            if detail_change_relevant:
                if self._should_defer_detail_refresh(refresh_reason=refresh_reason):
                    self._pending_background_refresh_sections.add(self.selected_section)
                else:
                    detail_changed = await self._render_detail_content(state)
                    self._pending_background_refresh_sections.discard(self.selected_section)
                    self._last_detail_apply_at[self.selected_section] = monotonic()
            detail_structure_changed = (
                previous_detail_signature is None or previous_detail_kind != self._detail_kind
            )
            if detail_structure_changed and self.focused_pane == "detail":
                self._schedule_focus_sync()

            self._status_signature = None
            self._refresh_keybind_bar()

            self._maybe_notify_refresh(refresh_reason=refresh_reason, detail_changed=detail_changed)

