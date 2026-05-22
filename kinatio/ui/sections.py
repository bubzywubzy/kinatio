"""Interactive section helpers for keyboard-first detail views."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha3_256
from itertools import count
from typing import Any, Literal

from rich.align import Align
from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from kinatio.domain.models import LogEntry, NetworkInterface, PackageEntry, PortEntry, ProcessEntry, ServiceEntry, SystemState
from kinatio.ui.log_noise import filter_known_log_noise
from kinatio.ui.layout import _bytes_to_text, _mbps_to_text, _timestamp_text

INTERACTIVE_SECTIONS = frozenset({"Processes", "Services", "Logs", "Network", "Interfaces", "Packages"})


@dataclass(slots=True)
class DetailViewState:
    section: str
    mode: Literal["list", "detail"] = "list"
    target: str | None = None
    cursor_key: str | None = None
    search_query: str = ""
    sort_key: str | None = None
    sort_desc: bool = True
    follow_enabled: bool = False
    live_updates_enabled: bool = False
    show_log_noise: bool = False


@dataclass(slots=True)
class InteractiveRow:
    key: str
    cells: tuple[str, ...]
    search_blob: str
    target: str | None = None


@dataclass(slots=True)
class InteractiveTableSpec:
    title: str
    subtitle: str
    columns: tuple[str, ...]
    rows: list[InteractiveRow]
    empty_message: str


PROCESS_SORT_SEQUENCE: tuple[tuple[str, bool], ...] = (
    ("cpu", True),
    ("memory", True),
    ("pid", False),
    ("name", False),
)

SERVICE_SORT_SEQUENCE: tuple[tuple[str, bool], ...] = (
    ("state", False),
    ("name", False),
    ("enabled", True),
)

LOG_SORT_SEQUENCE: tuple[tuple[str, bool], ...] = (
    ("timestamp", True),
    ("priority", False),
    ("unit", False),
)

NETWORK_SORT_SEQUENCE: tuple[tuple[str, bool], ...] = (
    ("state", False),
    ("name", False),
    ("rx", True),
    ("tx", True),
)

PACKAGE_SORT_SEQUENCE: tuple[tuple[str, bool], ...] = (
    ("update", False),
    ("name", False),
    ("version", False),
)


class InteractiveSectionView(Vertical):
    """Wrapper for an interactive section table plus contextual hints."""

    DEFAULT_CSS = """
    InteractiveSectionView {
        height: 1fr;
    }

    .interactive-section-title {
        color: #f5f6f7;
        text-style: bold;
        width: 100%;
        margin-bottom: 1;
    }

    .interactive-section-subtitle {
        color: #8c949b;
        width: 100%;
        margin-bottom: 1;
    }

    #interactive-table {
        height: 1fr;
        border: round #20262c;
    }
    """

    def __init__(self, spec: InteractiveTableSpec, *, selected_key: str | None = None) -> None:
        super().__init__()
        self.spec = spec
        self.selected_key = selected_key
        self.row_keys = [row.key for row in spec.rows]
        self.row_targets = {row.key: row.target or row.key for row in spec.rows}

    def compose(self) -> ComposeResult:
        yield Static(
            Text(self.spec.title, justify="center"),
            id="interactive-section-title",
            classes="interactive-section-title",
        )
        yield Static(
            Text(self.spec.subtitle, justify="center"),
            id="interactive-section-subtitle",
            classes="interactive-section-subtitle",
        )
        table = DataTable(
            id="interactive-table",
            show_row_labels=False,
            zebra_stripes=True,
            cursor_type="row",
        )
        for column in self.spec.columns:
            table.add_column(column)
        if self.spec.rows:
            for row in self.spec.rows:
                table.add_row(*row.cells, key=row.key)
        else:
            table.add_row(*([self.spec.empty_message] + ["" for _ in self.spec.columns[1:]]), key="__empty__")
        yield table

    def on_mount(self) -> None:
        table = self.query_one("#interactive-table", DataTable)
        if not self.row_keys:
            return
        if self.selected_key in self.row_keys:
            row_index = self.row_keys.index(self.selected_key)
        else:
            row_index = 0
        table.move_cursor(row=row_index, column=0, scroll=False)

    def focus_default(self) -> None:
        if self.row_keys:
            self.query_one("#interactive-table", DataTable).focus()

    def current_key(self) -> str | None:
        if not self.row_keys:
            return None
        table = self.query_one("#interactive-table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row < 0 or cursor_row >= len(self.row_keys):
            return None
        return self.row_keys[cursor_row]

    def current_target(self) -> str | None:
        row_key = self.current_key()
        if row_key is None:
            return None
        return self.row_targets.get(row_key, row_key)

    def resolve_target(self, row_key: str | None) -> str | None:
        if row_key is None:
            return None
        return self.row_targets.get(row_key, row_key)

    def update_spec(self, spec: InteractiveTableSpec, *, selected_key: str | None = None) -> None:
        self.spec = spec
        title = self.query_one("#interactive-section-title", Static)
        subtitle = self.query_one("#interactive-section-subtitle", Static)
        table = self.query_one("#interactive-table", DataTable)
        had_focus = table.has_focus
        current_key = self.current_key()

        effective_key = selected_key or current_key
        self.selected_key = effective_key
        self.row_keys = [row.key for row in spec.rows]
        self.row_targets = {row.key: row.target or row.key for row in spec.rows}

        title.update(Text(spec.title, justify="center"))
        subtitle.update(Text(spec.subtitle, justify="center"))
        table.clear(columns=True)
        for column in spec.columns:
            table.add_column(column)

        if spec.rows:
            for row in spec.rows:
                table.add_row(*row.cells, key=row.key)
        else:
            table.add_row(*([spec.empty_message] + ["" for _ in spec.columns[1:]]), key="__empty__")

        if self.row_keys:
            if effective_key in self.row_keys:
                row_index = self.row_keys.index(effective_key)
            else:
                row_index = 0
            table.move_cursor(row=row_index, column=0, scroll=False)

        if had_focus and self.row_keys:
            table.focus()


def is_interactive_section(section: str) -> bool:
    return section in INTERACTIVE_SECTIONS


def default_view_state(section: str, *, show_log_noise: bool = False) -> DetailViewState:
    sort_key, sort_desc = _sort_sequence_for(section)[0] if is_interactive_section(section) else (None, True)
    live_updates_enabled = is_interactive_section(section)
    return DetailViewState(
        section=section,
        sort_key=sort_key,
        sort_desc=sort_desc,
        follow_enabled=section == "Logs",
        live_updates_enabled=live_updates_enabled,
        show_log_noise=show_log_noise if section == "Logs" else False,
    )


def cycle_sort(section: str, current_key: str | None, current_desc: bool) -> tuple[str | None, bool]:
    sequence = _sort_sequence_for(section)
    if not sequence:
        return current_key, current_desc
    current = (current_key, current_desc)
    if current not in sequence:
        return sequence[0]
    index = sequence.index(current)
    return sequence[(index + 1) % len(sequence)]


def build_interactive_section(
    state: SystemState,
    view: DetailViewState,
    *,
    log_noise_patterns: Sequence[str] | None = None,
) -> InteractiveSectionView | None:
    spec = build_interactive_table_spec(state, view, log_noise_patterns=log_noise_patterns)
    if spec is None:
        return None
    return InteractiveSectionView(spec, selected_key=view.cursor_key)


def build_interactive_table_spec(
    state: SystemState,
    view: DetailViewState,
    *,
    log_noise_patterns: Sequence[str] | None = None,
) -> InteractiveTableSpec | None:
    if view.mode != "list":
        return None
    spec = _build_table_spec(state, view, log_noise_patterns=log_noise_patterns)
    if spec is None:
        return None
    spec = InteractiveTableSpec(
        title=spec.title,
        subtitle=spec.subtitle,
        columns=spec.columns,
        rows=_ensure_unique_row_keys(spec.rows),
        empty_message=spec.empty_message,
    )
    row_keys = [row.key for row in spec.rows]
    if view.section == "Logs" and view.follow_enabled and row_keys and view.cursor_key is None:
        view.cursor_key = row_keys[0]
    elif row_keys:
        if view.cursor_key not in row_keys:
            view.cursor_key = row_keys[0]
    else:
        view.cursor_key = None
    return spec


def interactive_spec_signature(spec: InteractiveTableSpec, *, selected_key: str | None = None) -> tuple[Any, ...]:
    return (
        spec.title,
        spec.subtitle,
        spec.columns,
        tuple((row.key, row.target, row.cells) for row in spec.rows),
        spec.empty_message,
        selected_key,
    )


def render_interactive_detail(
    state: SystemState,
    view: DetailViewState,
    *,
    log_noise_patterns: Sequence[str] | None = None,
) -> RenderableType | None:
    if view.mode != "detail" or view.target is None:
        return None
    if view.section == "Processes":
        return _render_process_detail(state, view.target)
    if view.section == "Services":
        return _render_service_detail(state, view.target)
    if view.section == "Logs":
        return _render_log_detail(state, view, log_noise_patterns=log_noise_patterns)
    if view.section in {"Network", "Interfaces"}:
        return _render_network_detail(state, view.target)
    if view.section == "Packages":
        return _render_package_detail(state, view.target)
    return None


def _centered_detail_group(*lines: RenderableType) -> RenderableType:
    return Align.center(
        Group(*(Align.center(line) for line in lines)),
        vertical="top",
    )


def _sort_sequence_for(section: str) -> tuple[tuple[str, bool], ...]:
    if section == "Processes":
        return PROCESS_SORT_SEQUENCE
    if section == "Services":
        return SERVICE_SORT_SEQUENCE
    if section == "Logs":
        return LOG_SORT_SEQUENCE
    if section in {"Network", "Interfaces"}:
        return NETWORK_SORT_SEQUENCE
    if section == "Packages":
        return PACKAGE_SORT_SEQUENCE
    return ()


def _build_table_spec(
    state: SystemState,
    view: DetailViewState,
    *,
    log_noise_patterns: Sequence[str] | None = None,
) -> InteractiveTableSpec | None:
    if view.section == "Processes":
        return _build_process_spec(state, view)
    if view.section == "Services":
        return _build_service_spec(state, view)
    if view.section == "Logs":
        return _build_logs_spec(state, view, log_noise_patterns=log_noise_patterns)
    if view.section in {"Network", "Interfaces"}:
        return _build_network_spec(state, view)
    if view.section == "Packages":
        return _build_packages_spec(state, view)
    return None


def _build_process_spec(state: SystemState, view: DetailViewState) -> InteractiveTableSpec:
    entries = _filter_processes(state.processes.entries, view.search_query)
    entries = _sort_processes(entries, view.sort_key or "cpu", view.sort_desc)
    sort_label = _sort_label("Processes", view.sort_key or "cpu", view.sort_desc)
    filter_label = view.search_query or "none"
    subtitle = (
        f"{len(entries)} shown of {state.processes.total_processes} tracked · "
        f"sort {sort_label} · filter {filter_label} · Enter detail"
    )
    rows = [
        InteractiveRow(
            key=str(entry.pid),
            cells=(
                str(entry.pid),
                entry.name,
                entry.username or "-",
                f"{entry.cpu_percent:.1f}%",
                f"{entry.memory_percent:.1f}%",
                entry.status or "-",
            ),
            search_blob=" ".join(
                [
                    str(entry.pid),
                    entry.name,
                    entry.username or "",
                    entry.status or "",
                    entry.command,
                ]
            ).casefold(),
            target=str(entry.pid),
        )
        for entry in entries
    ]
    return InteractiveTableSpec(
        title="Processes",
        subtitle=subtitle,
        columns=("PID", "Name", "User", "CPU", "Mem", "State"),
        rows=rows,
        empty_message="No processes matched the current filter.",
    )


def _build_service_spec(state: SystemState, view: DetailViewState) -> InteractiveTableSpec:
    services = _filter_services(state.services.services, view.search_query)
    services = _sort_services(services, view.sort_key or "state", view.sort_desc)
    failed_services = sum(1 for service in state.services.services if service.is_failed)
    sort_label = _sort_label("Services", view.sort_key or "state", view.sort_desc)
    filter_label = view.search_query or "none"
    subtitle = (
        f"{len(services)} shown of {len(state.services.services)} units · "
        f"failed {failed_services} · sort {sort_label} · filter {filter_label} · Enter detail"
    )
    rows = [
        InteractiveRow(
            key=service.name,
            cells=(
                service.name,
                service.active_state,
                service.sub_state,
                "yes" if service.is_enabled else "no",
                service.description or "-",
            ),
            search_blob=" ".join(
                [
                    service.name,
                    service.active_state,
                    service.sub_state,
                    service.description,
                    service.unit_file_state,
                ]
            ).casefold(),
            target=service.name,
        )
        for service in services
    ]
    return InteractiveTableSpec(
        title="Services",
        subtitle=subtitle,
        columns=("Unit", "Active", "Sub", "Enabled", "Description"),
        rows=rows,
        empty_message="No services matched the current filter.",
    )


def _build_logs_spec(
    state: SystemState,
    view: DetailViewState,
    *,
    log_noise_patterns: Sequence[str] | None = None,
) -> InteractiveTableSpec:
    matched_entries = _filter_logs(state.logs.entries, view.search_query)
    noise_result = filter_known_log_noise(
        matched_entries,
        show_known_noise=view.show_log_noise,
        patterns=log_noise_patterns,
    )
    entries = _sort_logs(noise_result.visible_entries, view.sort_key or "timestamp", view.sort_desc)
    visible_entries = entries[:200]
    sort_label = _sort_label("Logs", view.sort_key or "timestamp", view.sort_desc)
    filter_label = view.search_query or "none"
    noise_label = (
        "showing known environment noise"
        if view.show_log_noise
        else f"noise hidden {noise_result.suppressed_count}"
    )
    subtitle = (
        f"{len(visible_entries)} shown of {len(matched_entries)} matched entries · "
        f"live {'on' if state.logs.live_enabled else 'off'} · follow {'on' if view.follow_enabled else 'paused'} · sort {sort_label} · "
        f"filter {filter_label} · {noise_label} · N {'hide' if view.show_log_noise else 'show'} noise · Enter detail"
    )
    rows = [
        InteractiveRow(
            key=row_key,
            cells=(
                _timestamp_text(entry.timestamp),
                (entry.priority or "-").upper(),
                entry.unit or entry.source,
                entry.message,
            ),
            search_blob=" ".join(
                [
                    _timestamp_text(entry.timestamp),
                    entry.priority or "",
                    entry.unit or "",
                    entry.source,
                    entry.message,
                ]
            ).casefold(),
            target=row_key,
        )
        for row_key, entry in _iter_log_rows(visible_entries)
    ]
    return InteractiveTableSpec(
        title="Logs",
        subtitle=subtitle,
        columns=("Time", "Priority", "Unit", "Message"),
        rows=rows,
        empty_message=(
            "No log entries matched after hiding known environment noise. Press N to show them."
            if noise_result.suppressed_count and not view.show_log_noise
            else "No log entries matched the current filter."
        ),
    )


def _build_network_spec(state: SystemState, view: DetailViewState) -> InteractiveTableSpec:
    interfaces = _filter_interfaces(state.network.interfaces, view.search_query)
    interfaces = _sort_interfaces(interfaces, view.sort_key or "state", view.sort_desc)
    firewall_state = state.network.firewall.backend or "none"
    if state.network.firewall.enabled is not None:
        firewall_state = f"{firewall_state} {'on' if state.network.firewall.enabled else 'off'}"
    sort_label = _sort_label("Interfaces", view.sort_key or "state", view.sort_desc)
    filter_label = view.search_query or "none"
    subtitle = (
        f"{len(interfaces)} interfaces · routes {len(state.network.routes)} · ports {len(state.network.listening_ports)} · "
        f"firewall {firewall_state} · sort {sort_label} · filter {filter_label} · Enter detail"
    )
    rows = [
        InteractiveRow(
            key=interface.name,
            cells=(
                interface.name,
                "up" if interface.is_up else "down",
                interface.addresses[0].address if interface.addresses else "-",
                _bytes_to_text(interface.rx_bytes),
                _bytes_to_text(interface.tx_bytes),
                _mbps_to_text(interface.speed_mbps, unavailable="-"),
            ),
            search_blob=" ".join(
                [
                    interface.name,
                    interface.mac_address or "",
                    "up" if interface.is_up else "down",
                    *(address.address for address in interface.addresses),
                ]
            ).casefold(),
            target=interface.name,
        )
        for interface in interfaces
    ]
    return InteractiveTableSpec(
        title="Interfaces" if view.section == "Interfaces" else "Network",
        subtitle=subtitle,
        columns=("Interface", "State", "Address", "RX", "TX", "Speed"),
        rows=rows,
        empty_message="No network interfaces matched the current filter.",
    )


def _build_packages_spec(state: SystemState, view: DetailViewState) -> InteractiveTableSpec:
    entries = _filter_packages(state.packages.entries, view.search_query)
    entries = _sort_packages(entries, view.sort_key or "update", view.sort_desc)
    updates_label = str(state.packages.update_count) if state.packages.update_count is not None else "n/a"
    sort_label = _sort_label("Packages", view.sort_key or "update", view.sort_desc)
    filter_label = view.search_query or "none"
    subtitle = (
        f"{len(entries)} shown of {len(state.packages.entries)} sampled · "
        f"manager {state.packages.manager or 'n/a'} · updates {updates_label} · "
        f"sort {sort_label} · filter {filter_label} · Enter detail"
    )
    rows = [
        InteractiveRow(
            key=entry.name,
            cells=(
                entry.name,
                entry.version,
                entry.update_version or "current",
                entry.architecture or "-",
            ),
            search_blob=" ".join(
                [
                    entry.name,
                    entry.version,
                    entry.architecture or "",
                    entry.update_version or "",
                    entry.summary or "",
                ]
            ).casefold(),
            target=entry.name,
        )
        for entry in entries
    ]
    return InteractiveTableSpec(
        title="Packages",
        subtitle=subtitle,
        columns=("Name", "Version", "Update", "Arch"),
        rows=rows,
        empty_message="No packages matched the current filter.",
    )


def _filter_processes(entries: list[ProcessEntry], query: str) -> list[ProcessEntry]:
    normalized = query.strip().casefold()
    if not normalized:
        return list(entries)
    return [
        entry
        for entry in entries
        if normalized in " ".join(
            [
                str(entry.pid),
                entry.name,
                entry.username or "",
                entry.status or "",
                entry.command,
            ]
        ).casefold()
    ]


def _filter_services(entries: list[ServiceEntry], query: str) -> list[ServiceEntry]:
    normalized = query.strip().casefold()
    if not normalized:
        return list(entries)
    return [
        entry
        for entry in entries
        if normalized in " ".join(
            [
                entry.name,
                entry.active_state,
                entry.sub_state,
                entry.description,
                entry.unit_file_state,
            ]
        ).casefold()
    ]


def _filter_logs(entries: list[LogEntry], query: str) -> list[LogEntry]:
    normalized = query.strip().casefold()
    if not normalized:
        return list(entries)
    return [
        entry
        for entry in entries
        if normalized in " ".join(
            [
                _timestamp_text(entry.timestamp),
                entry.priority or "",
                entry.unit or "",
                entry.source,
                entry.message,
            ]
        ).casefold()
    ]


def _filter_interfaces(entries: list[NetworkInterface], query: str) -> list[NetworkInterface]:
    normalized = query.strip().casefold()
    if not normalized:
        return list(entries)
    return [
        entry
        for entry in entries
        if normalized in " ".join(
            [
                entry.name,
                entry.mac_address or "",
                "up" if entry.is_up else "down",
                *(address.address for address in entry.addresses),
            ]
        ).casefold()
    ]


def _filter_packages(entries: list[PackageEntry], query: str) -> list[PackageEntry]:
    normalized = query.strip().casefold()
    if not normalized:
        return list(entries)
    return [
        entry
        for entry in entries
        if normalized in " ".join(
            [
                entry.name,
                entry.version,
                entry.architecture or "",
                entry.update_version or "",
                entry.summary or "",
            ]
        ).casefold()
    ]


def _sort_processes(entries: list[ProcessEntry], key: str, descending: bool) -> list[ProcessEntry]:
    if key == "memory":
        return sorted(entries, key=lambda entry: (entry.memory_percent, entry.cpu_percent, entry.pid), reverse=descending)
    if key == "pid":
        return sorted(entries, key=lambda entry: entry.pid, reverse=descending)
    if key == "name":
        return sorted(entries, key=lambda entry: (entry.name.casefold(), entry.pid), reverse=descending)
    return sorted(entries, key=lambda entry: (entry.cpu_percent, entry.memory_percent, entry.pid), reverse=descending)


def _service_state_rank(service: ServiceEntry) -> tuple[int, str, str]:
    if service.is_failed or service.active_state == "failed":
        return (0, service.active_state, service.name.casefold())
    if service.active_state == "active":
        return (1, service.active_state, service.name.casefold())
    return (2, service.active_state, service.name.casefold())


def _sort_services(entries: list[ServiceEntry], key: str, descending: bool) -> list[ServiceEntry]:
    if key == "name":
        return sorted(entries, key=lambda entry: entry.name.casefold(), reverse=descending)
    if key == "enabled":
        return sorted(entries, key=lambda entry: (entry.is_enabled, not entry.is_failed, entry.name.casefold()), reverse=descending)
    return sorted(entries, key=_service_state_rank, reverse=descending)


def _priority_rank(priority: str | None) -> tuple[int, str]:
    normalized = (priority or "").lower()
    ranks = {
        "0": 0,
        "1": 1,
        "2": 2,
        "3": 3,
        "crit": 2,
        "critical": 2,
        "err": 3,
        "error": 3,
        "warning": 4,
        "warn": 4,
        "notice": 5,
        "info": 6,
        "debug": 7,
    }
    return (ranks.get(normalized, 8), normalized or "-")


def _sort_logs(entries: list[LogEntry], key: str, descending: bool) -> list[LogEntry]:
    if key == "priority":
        return sorted(entries, key=lambda entry: (_priority_rank(entry.priority), entry.timestamp), reverse=descending)
    if key == "unit":
        return sorted(entries, key=lambda entry: ((entry.unit or entry.source).casefold(), entry.timestamp), reverse=descending)
    return sorted(entries, key=lambda entry: entry.timestamp, reverse=descending)


def _sort_interfaces(entries: list[NetworkInterface], key: str, descending: bool) -> list[NetworkInterface]:
    if key == "name":
        return sorted(entries, key=lambda entry: entry.name.casefold(), reverse=descending)
    if key == "rx":
        return sorted(entries, key=lambda entry: (entry.rx_bytes, entry.tx_bytes, entry.name.casefold()), reverse=descending)
    if key == "tx":
        return sorted(entries, key=lambda entry: (entry.tx_bytes, entry.rx_bytes, entry.name.casefold()), reverse=descending)
    return sorted(entries, key=lambda entry: (not entry.is_up, entry.name.casefold()), reverse=descending)


def _sort_packages(entries: list[PackageEntry], key: str, descending: bool) -> list[PackageEntry]:
    if key == "name":
        return sorted(entries, key=lambda entry: (entry.name.casefold(), entry.version.casefold()), reverse=descending)
    if key == "version":
        return sorted(entries, key=lambda entry: (entry.version.casefold(), entry.name.casefold()), reverse=descending)
    return sorted(
        entries,
        key=lambda entry: (
            entry.update_version is None,
            entry.name.casefold(),
            (entry.update_version or entry.version).casefold(),
        ),
        reverse=descending,
    )


def _sort_label(section: str, key: str, descending: bool) -> str:
    del descending
    labels = {
        "Processes": {
            "cpu": "cpu desc",
            "memory": "memory desc",
            "pid": "pid asc",
            "name": "name asc",
        },
        "Services": {
            "state": "state priority",
            "name": "name asc",
            "enabled": "enabled first",
        },
        "Logs": {
            "timestamp": "newest first",
            "priority": "priority",
            "unit": "unit asc",
        },
        "Network": {
            "state": "up first",
            "name": "name asc",
            "rx": "rx desc",
            "tx": "tx desc",
        },
        "Interfaces": {
            "state": "up first",
            "name": "name asc",
            "rx": "rx desc",
            "tx": "tx desc",
        },
        "Packages": {
            "update": "updates first",
            "name": "name asc",
            "version": "version asc",
        },
    }
    return labels.get(section, {}).get(key, key)


def _ensure_unique_row_keys(rows: list[InteractiveRow]) -> list[InteractiveRow]:
    seen_counts: dict[str, int] = {}
    unique_rows: list[InteractiveRow] = []
    for row in rows:
        occurrence = seen_counts.get(row.key, 0)
        seen_counts[row.key] = occurrence + 1
        if occurrence == 0:
            unique_rows.append(row)
            continue
        unique_rows.append(
            InteractiveRow(
                key=f"{row.key}-{occurrence}",
                cells=row.cells,
                search_blob=row.search_blob,
                target=row.target or row.key,
            )
        )
    return unique_rows


def _log_entry_key(entry: LogEntry) -> str:
    fingerprint = "|".join(
        [
            _timestamp_text(entry.timestamp),
            entry.source,
            entry.unit or "",
            entry.priority or "",
            entry.message,
        ]
    )
    return sha3_256(fingerprint.encode("utf-8")).hexdigest()[:16]


def _iter_log_rows(entries: list[LogEntry]) -> list[tuple[str, LogEntry]]:
    duplicate_counts: dict[str, Any] = {}
    rows: list[tuple[str, LogEntry]] = []
    for entry in entries:
        base_key = _log_entry_key(entry)
        occurrence_counter = duplicate_counts.setdefault(base_key, count())
        occurrence = next(occurrence_counter)
        row_key = base_key if occurrence == 0 else f"{base_key}-{occurrence}"
        rows.append((row_key, entry))
    return rows


def _render_process_detail(state: SystemState, target: str) -> RenderableType:
    process = next((entry for entry in state.processes.entries if str(entry.pid) == target), None)
    if process is None:
        return _centered_detail_group(
            Text("PROCESS DETAIL", style="bold white"),
            Text(),
            Text(f"PID {target} is no longer present in the current snapshot.", style="bold red"),
            Text("Press Escape to return to the live process list.", style="grey70"),
        )
    lines: list[Text] = [
        Text("PROCESS DETAIL", style="bold white"),
        Text(f"pid {process.pid} · {process.name}", style="grey70"),
        Text(),
        Text.assemble(("USER ", "grey50"), (process.username or "n/a", "white")),
        Text.assemble(("STATE ", "grey50"), (process.status or "n/a", "white")),
        Text.assemble(("CPU ", "grey50"), (f"{process.cpu_percent:.1f}%", "white")),
        Text.assemble(("MEM ", "grey50"), (f"{process.memory_percent:.1f}%", "white")),
        Text.assemble(("RSS ", "grey50"), (_bytes_to_text(process.rss_bytes), "white")),
        Text(),
        Text("COMMAND", style="bold grey70"),
        Text(process.command or "No command line was captured for this process.", style="grey62"),
        Text(),
        Text("Press Escape to return to the live process list.", style="grey70"),
    ]
    return _centered_detail_group(*lines)


def _render_service_detail(state: SystemState, target: str) -> RenderableType:
    service = next((entry for entry in state.services.services if entry.name == target), None)
    if service is None:
        return _centered_detail_group(
            Text("SERVICE DETAIL", style="bold white"),
            Text(),
            Text(f"{target} is no longer present in the current snapshot.", style="bold red"),
            Text("Press Escape to return to the live services list.", style="grey70"),
        )
    lines: list[Text] = [
        Text("SERVICE DETAIL", style="bold white"),
        Text(service.name, style="grey70"),
        Text(),
        Text.assemble(("MANAGER ", "grey50"), ((state.services.manager or "n/a"), "white")),
        Text.assemble(("ACTIVE ", "grey50"), (service.active_state, "white")),
        Text.assemble(("SUB ", "grey50"), (service.sub_state, "white")),
        Text.assemble(("LOAD ", "grey50"), (service.load_state, "white")),
        Text.assemble(("ENABLED ", "grey50"), ("yes" if service.is_enabled else "no", "white")),
        Text.assemble(("UNIT FILE ", "grey50"), (service.unit_file_state, "white")),
        Text(),
        Text("DESCRIPTION", style="bold grey70"),
        Text(service.description or "No description was reported for this unit.", style="grey62"),
        Text(),
        Text("Press Escape to return to the live services list.", style="grey70"),
    ]
    return _centered_detail_group(*lines)


def _render_log_detail(
    state: SystemState,
    view: DetailViewState,
    *,
    log_noise_patterns: Sequence[str] | None = None,
) -> RenderableType:
    matched_entries = _filter_logs(state.logs.entries, view.search_query)
    noise_result = filter_known_log_noise(
        matched_entries,
        show_known_noise=view.show_log_noise,
        patterns=log_noise_patterns,
    )
    entries = _sort_logs(noise_result.visible_entries, view.sort_key or "timestamp", view.sort_desc)[:200]
    entry = next((candidate for row_key, candidate in _iter_log_rows(entries) if row_key == view.target), None)
    if entry is None:
        return _centered_detail_group(
            Text("LOG DETAIL", style="bold white"),
            Text(),
            Text("The selected log entry is no longer present in the current snapshot.", style="bold red"),
            Text("Press Escape to return to the live log list.", style="grey70"),
        )
    lines: list[Text] = [
        Text("LOG DETAIL", style="bold white"),
        Text(_timestamp_text(entry.timestamp), style="grey70"),
        Text(),
        Text.assemble(("PRIORITY ", "grey50"), (((entry.priority or "-").upper()), "white")),
        Text.assemble(("UNIT ", "grey50"), ((entry.unit or "-"), "white")),
        Text.assemble(("SOURCE ", "grey50"), (entry.source, "white")),
        Text(),
        Text("MESSAGE", style="bold grey70"),
        Text(entry.message or "No log message was captured.", style="grey62"),
        Text(),
        Text(
            "Press Escape to return · Use / to filter the list again.",
            style="grey70",
        ),
    ]
    return _centered_detail_group(*lines)


def _render_network_detail(state: SystemState, target: str) -> RenderableType:
    interface = next((candidate for candidate in state.network.interfaces if candidate.name == target), None)
    if interface is None:
        return _centered_detail_group(
            Text("INTERFACE DETAIL", style="bold white"),
            Text(),
            Text(f"Interface {target} is no longer present in the current snapshot.", style="bold red"),
            Text("Press Escape to return to the live interface list.", style="grey70"),
        )

    routes = [route for route in state.network.routes if route.device == interface.name]
    addresses = interface.addresses or []
    address_values = {address.address for address in addresses}
    wildcard_addresses = {"0.0.0.0", "::", "*"}
    related_ports = [
        port
        for port in state.network.listening_ports
        if port.local_address in address_values or port.local_address in wildcard_addresses
    ]

    lines: list[Text] = [
        Text("INTERFACE DETAIL", style="bold white"),
        Text(interface.name, style="grey70"),
        Text(),
        Text.assemble(("STATE ", "grey50"), (("up" if interface.is_up else "down"), "white")),
        Text.assemble(("MAC ", "grey50"), ((interface.mac_address or "n/a"), "white")),
        Text.assemble(("MTU ", "grey50"), (str(interface.mtu or "n/a"), "white")),
        Text.assemble(("SPEED ", "grey50"), (_mbps_to_text(interface.speed_mbps), "white")),
        Text.assemble(("RX ", "grey50"), (_bytes_to_text(interface.rx_bytes), "white")),
        Text.assemble(("TX ", "grey50"), (_bytes_to_text(interface.tx_bytes), "white")),
        Text(),
        Text("ADDRESSES", style="bold grey70"),
    ]
    if addresses:
        for address in addresses:
            detail = address.family
            if address.netmask:
                detail = f"{detail} netmask {address.netmask}"
            lines.append(Text(f"{address.address}  {detail}", style="grey62"))
    else:
        lines.append(Text("No addresses are currently assigned to this interface.", style="grey62"))

    lines.extend([Text(), Text("ROUTES", style="bold grey70")])
    if routes:
        for route in routes[:8]:
            lines.append(
                Text.assemble(
                    (route.destination, "white"),
                    (" via ", "grey50"),
                    (route.gateway or "-", "grey62"),
                    (" metric ", "grey50"),
                    (str(route.metric or "-"), "grey62"),
                )
            )
    else:
        lines.append(Text("No routes are currently tied to this interface.", style="grey62"))

    lines.extend([Text(), Text("LISTENING PORTS", style="bold grey70")])
    if related_ports:
        for port in related_ports[:8]:
            lines.append(_format_port_line(port))
    else:
        lines.append(Text("No listening ports are currently associated with this interface address set.", style="grey62"))

    firewall_state = state.network.firewall.backend or "none"
    if state.network.firewall.enabled is not None:
        firewall_state = f"{firewall_state} {'enabled' if state.network.firewall.enabled else 'disabled'}"
    lines.extend(
        [
            Text(),
            Text.assemble(("FIREWALL ", "grey50"), (firewall_state, "white")),
            Text.assemble(("DNS ", "grey50"), (", ".join(state.network.dns.servers) or "n/a", "white")),
            Text(),
            Text("Press Escape to return to the live interface list.", style="grey70"),
        ]
    )
    return _centered_detail_group(*lines)


def _render_package_detail(state: SystemState, target: str) -> RenderableType:
    package = next((entry for entry in state.packages.entries if entry.name == target), None)
    if package is None:
        return _centered_detail_group(
            Text("PACKAGE DETAIL", style="bold white"),
            Text(),
            Text(f"{target} is no longer present in the current package sample.", style="bold red"),
            Text("Press Escape to return to the package list.", style="grey70"),
        )

    lines: list[Text] = [
        Text("PACKAGE DETAIL", style="bold white"),
        Text(package.name, style="grey70"),
        Text(),
        Text.assemble(("MANAGER ", "grey50"), ((state.packages.manager or "n/a"), "white")),
        Text.assemble(("VERSION ", "grey50"), (package.version, "white")),
        Text.assemble(("UPDATE ", "grey50"), ((package.update_version or "current"), "white" if package.update_version else "grey62")),
        Text.assemble(("ARCH ", "grey50"), ((package.architecture or "n/a"), "white")),
        Text(),
        Text("SUMMARY", style="bold grey70"),
        Text(package.summary or "No package summary was captured in the bounded sample.", style="grey62"),
        Text(),
        Text("Press Escape to return · Use / to filter the list again.", style="grey70"),
    ]
    return _centered_detail_group(*lines)


def _format_port_line(port: PortEntry) -> Text:
    process_text = port.process_name or (str(port.pid) if port.pid is not None else "unknown")
    return Text.assemble(
        (f"{port.protocol.upper()} {port.local_address}:{port.local_port}", "white"),
        ("  ", ""),
        (process_text, "grey62"),
    )