from rich.align import Align
from rich.console import Console
from datetime import UTC, datetime

from kinatio.domain.models import LogEntry, LogsState, NetworkAddress, NetworkInterface, NetworkState, PackageEntry, PackagesState, PortEntry, ProcessEntry, ProcessesState, RouteEntry, ServiceEntry, ServicesState, SystemState
from kinatio.ui.sections import DetailViewState, _log_entry_key, build_interactive_section, cycle_sort, default_view_state, render_interactive_detail


def _render_plain_text(renderable: object) -> str:
    console = Console(width=140)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_default_view_state_uses_section_specific_sort_defaults() -> None:
    process_view = default_view_state("Processes")
    service_view = default_view_state("Services")
    logs_view = default_view_state("Logs")
    network_view = default_view_state("Network")
    interfaces_view = default_view_state("Interfaces")
    packages_view = default_view_state("Packages")
    overview_view = default_view_state("Overview")

    assert (process_view.sort_key, process_view.sort_desc) == ("cpu", True)
    assert (service_view.sort_key, service_view.sort_desc) == ("state", False)
    assert (logs_view.sort_key, logs_view.sort_desc) == ("timestamp", True)
    assert (network_view.sort_key, network_view.sort_desc) == ("state", False)
    assert (interfaces_view.sort_key, interfaces_view.sort_desc) == ("state", False)
    assert (packages_view.sort_key, packages_view.sort_desc) == ("update", False)
    assert logs_view.follow_enabled is True
    assert process_view.live_updates_enabled is True
    assert service_view.live_updates_enabled is True
    assert network_view.live_updates_enabled is True
    assert interfaces_view.live_updates_enabled is True
    assert packages_view.live_updates_enabled is True
    assert logs_view.live_updates_enabled is True
    assert logs_view.show_log_noise is False
    assert overview_view.sort_key is None


def test_cycle_sort_rotates_process_sort_modes() -> None:
    assert cycle_sort("Processes", "cpu", True) == ("memory", True)
    assert cycle_sort("Processes", "memory", True) == ("pid", False)
    assert cycle_sort("Processes", "pid", False) == ("name", False)


def test_build_interactive_process_section_filters_and_orders_rows() -> None:
    state = SystemState(
        processes=ProcessesState(
            total_processes=3,
            entries=[
                ProcessEntry(pid=10, name="alpha", username="root", cpu_percent=12.0, memory_percent=1.0),
                ProcessEntry(pid=20, name="beta", username="alice", cpu_percent=88.0, memory_percent=4.0),
                ProcessEntry(pid=30, name="gamma", username="bob", cpu_percent=42.0, memory_percent=2.0),
            ],
        )
    )
    view = DetailViewState(section="Processes", search_query="a", sort_key="cpu", sort_desc=True)

    widget = build_interactive_section(state, view)

    assert widget is not None
    assert [row.key for row in widget.spec.rows] == ["20", "30", "10"]


def test_render_process_detail_surfaces_selected_command() -> None:
    state = SystemState(
        processes=ProcessesState(
            entries=[
                ProcessEntry(
                    pid=4242,
                    name="python",
                    username="alice",
                    status="running",
                    cpu_percent=25.0,
                    memory_percent=7.5,
                    command="python monitor.py",
                )
            ]
        )
    )

    renderable = render_interactive_detail(state, DetailViewState(section="Processes", mode="detail", target="4242"))

    assert isinstance(renderable, Align)

    rendered = _render_plain_text(renderable)

    assert "python monitor.py" in rendered
    assert "Press Escape to return" in rendered
    assert "Press X" not in rendered


def test_render_service_detail_surfaces_service_metadata() -> None:
    state = SystemState(
        services=ServicesState(
            manager="systemd",
            services=[
                ServiceEntry(
                    name="sshd.service",
                    active_state="active",
                    sub_state="running",
                    description="OpenSSH server daemon",
                    unit_file_state="enabled",
                    is_enabled=True,
                )
            ]
        )
    )

    renderable = render_interactive_detail(state, DetailViewState(section="Services", mode="detail", target="sshd.service"))

    assert isinstance(renderable, Align)

    rendered = _render_plain_text(renderable)

    assert "OpenSSH server daemon" in rendered
    assert "sshd.service" in rendered
    assert "systemd" in rendered
    assert "Press X" not in rendered


def test_build_interactive_logs_section_filters_by_message_text() -> None:
    state = SystemState(
        logs=LogsState(
            entries=[
                LogEntry(
                    timestamp=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
                    source="journal",
                    unit="sshd.service",
                    priority="info",
                    message="Accepted publickey for alice",
                ),
                LogEntry(
                    timestamp=datetime(2026, 5, 14, 12, 1, tzinfo=UTC),
                    source="journal",
                    unit="kernel",
                    priority="warning",
                    message="Link is down",
                ),
            ]
        )
    )

    widget = build_interactive_section(
        state,
        DetailViewState(section="Logs", search_query="publickey", sort_key="timestamp", sort_desc=True),
    )

    assert widget is not None
    assert len(widget.spec.rows) == 1
    assert widget.spec.rows[0].cells[2] == "sshd.service"


def test_build_interactive_logs_section_tracks_newest_row_when_follow_enabled() -> None:
    state = SystemState(
        logs=LogsState(
            entries=[
                LogEntry(
                    timestamp=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
                    source="journal",
                    unit="sshd.service",
                    priority="info",
                    message="Older entry",
                ),
                LogEntry(
                    timestamp=datetime(2026, 5, 14, 12, 2, tzinfo=UTC),
                    source="journal",
                    unit="kernel",
                    priority="warning",
                    message="Newest entry",
                ),
            ]
        )
    )
    view = DetailViewState(section="Logs", sort_key="timestamp", sort_desc=True, follow_enabled=True)

    widget = build_interactive_section(state, view)

    assert widget is not None
    assert view.cursor_key == widget.spec.rows[0].key
    assert widget.spec.rows[0].cells[3] == "Newest entry"


def test_build_interactive_logs_section_hides_known_environment_noise_by_default() -> None:
    state = SystemState(
        logs=LogsState(
            entries=[
                LogEntry(
                    timestamp=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
                    source="kwin",
                    unit="kwin_wayland",
                    priority="warning",
                    message="window.tile is deprecated: use tile.manage() instead",
                ),
                LogEntry(
                    timestamp=datetime(2026, 5, 14, 12, 1, tzinfo=UTC),
                    source="journal",
                    unit="sshd.service",
                    priority="info",
                    message="Accepted publickey for alice",
                ),
            ]
        )
    )

    widget = build_interactive_section(
        state,
        DetailViewState(section="Logs", sort_key="timestamp", sort_desc=True),
    )

    assert widget is not None
    assert len(widget.spec.rows) == 1
    assert widget.spec.rows[0].cells[3] == "Accepted publickey for alice"
    assert "noise hidden 1" in widget.spec.subtitle.lower()


def test_build_interactive_logs_section_can_reveal_known_environment_noise() -> None:
    state = SystemState(
        logs=LogsState(
            entries=[
                LogEntry(
                    timestamp=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
                    source="kwin",
                    unit="kwin_wayland",
                    priority="warning",
                    message="workspace.tilingForScreen() is deprecated: use workspace.rootTile() instead",
                ),
                LogEntry(
                    timestamp=datetime(2026, 5, 14, 12, 1, tzinfo=UTC),
                    source="journal",
                    unit="sshd.service",
                    priority="info",
                    message="Accepted publickey for alice",
                ),
            ]
        )
    )

    widget = build_interactive_section(
        state,
        DetailViewState(section="Logs", sort_key="timestamp", sort_desc=True, show_log_noise=True),
    )

    assert widget is not None
    assert len(widget.spec.rows) == 2
    assert widget.spec.rows[0].cells[3] == "Accepted publickey for alice"
    assert widget.spec.rows[1].cells[3] == "workspace.tilingForScreen() is deprecated: use workspace.rootTile() instead"
    assert "showing known environment noise" in widget.spec.subtitle.lower()


def test_render_log_detail_surfaces_full_message() -> None:
    entry = LogEntry(
        timestamp=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        source="journal",
        unit="sshd.service",
        priority="err",
        message="Failed password for invalid user root",
    )
    state = SystemState(logs=LogsState(entries=[entry]))
    widget = build_interactive_section(
        state,
        DetailViewState(section="Logs", sort_key="timestamp", sort_desc=True),
    )

    assert widget is not None
    target = widget.spec.rows[0].key
    renderable = render_interactive_detail(state, DetailViewState(section="Logs", mode="detail", target=target))

    assert isinstance(renderable, Align)

    rendered = _render_plain_text(renderable)

    assert "Failed password for invalid user root" in rendered
    assert "LOG DETAIL" in rendered


def test_build_interactive_network_section_orders_up_interfaces_first() -> None:
    state = SystemState(
        network=NetworkState(
            interfaces=[
                NetworkInterface(name="eth0", is_up=False, rx_bytes=50, tx_bytes=70),
                NetworkInterface(name="wlan0", is_up=True, rx_bytes=500, tx_bytes=700),
            ]
        )
    )

    widget = build_interactive_section(
        state,
        DetailViewState(section="Network", sort_key="state", sort_desc=False),
    )

    assert widget is not None
    assert [row.key for row in widget.spec.rows] == ["wlan0", "eth0"]
    assert "x firewall" not in widget.spec.subtitle.lower()


def test_build_interactive_interfaces_section_uses_split_network_child_title() -> None:
    state = SystemState(
        network=NetworkState(
            interfaces=[
                NetworkInterface(name="eth0", is_up=True, rx_bytes=50, tx_bytes=70),
            ]
        )
    )

    widget = build_interactive_section(
        state,
        DetailViewState(section="Interfaces", sort_key="state", sort_desc=False),
    )

    assert widget is not None
    assert widget.spec.title == "Interfaces"
    assert widget.spec.rows[0].key == "eth0"


def test_build_interactive_packages_section_prioritizes_updates_and_filters_rows() -> None:
    state = SystemState(
        packages=PackagesState(
            manager="pacman",
            installed_count=3,
            update_count=1,
            entries=[
                PackageEntry(name="vim", version="9.1.1"),
                PackageEntry(name="bash", version="5.2", update_version="5.3", summary="GNU shell"),
                PackageEntry(name="curl", version="8.8.0"),
            ],
        )
    )

    widget = build_interactive_section(
        state,
        DetailViewState(section="Packages", search_query="", sort_key="update", sort_desc=False),
    )

    assert widget is not None
    assert [row.key for row in widget.spec.rows] == ["bash", "curl", "vim"]
    assert "updates 1" in widget.spec.subtitle.lower()

    filtered = build_interactive_section(
        state,
        DetailViewState(section="Packages", search_query="gnu", sort_key="update", sort_desc=False),
    )

    assert filtered is not None
    assert [row.key for row in filtered.spec.rows] == ["bash"]


def test_render_package_detail_surfaces_manager_update_and_summary() -> None:
    state = SystemState(
        packages=PackagesState(
            manager="dpkg",
            entries=[
                PackageEntry(
                    name="bash",
                    version="5.2",
                    architecture="amd64",
                    update_version="5.3",
                    summary="The GNU Bourne Again shell",
                )
            ],
        )
    )

    renderable = render_interactive_detail(state, DetailViewState(section="Packages", mode="detail", target="bash"))

    assert isinstance(renderable, Align)

    rendered = _render_plain_text(renderable)

    assert "PACKAGE DETAIL" in rendered
    assert "dpkg" in rendered
    assert "5.3" in rendered
    assert "The GNU Bourne Again shell" in rendered


def test_render_network_detail_surfaces_routes_and_ports() -> None:
    state = SystemState(
        network=NetworkState(
            interfaces=[
                NetworkInterface(
                    name="eth0",
                    is_up=True,
                    mac_address="00:11:22:33:44:55",
                    mtu=1500,
                    speed_mbps=1000,
                    addresses=[NetworkAddress(family="inet", address="192.168.1.5", netmask="255.255.255.0")],
                    rx_bytes=2048,
                    tx_bytes=1024,
                )
            ],
            routes=[RouteEntry(destination="default", gateway="192.168.1.1", device="eth0", metric=100)],
            listening_ports=[PortEntry(protocol="tcp", local_address="192.168.1.5", local_port=22, process_name="sshd")],
        )
    )

    renderable = render_interactive_detail(state, DetailViewState(section="Network", mode="detail", target="eth0"))

    assert isinstance(renderable, Align)

    rendered = _render_plain_text(renderable)

    assert "192.168.1.1" in rendered
    assert "sshd" in rendered
    assert "INTERFACE DETAIL" in rendered
    assert "1000 Mb/s" in rendered


def test_log_entry_key_is_deterministic_for_stable_row_identity() -> None:
    entry = LogEntry(
        timestamp=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        source="journal",
        unit="sshd.service",
        priority="info",
        message="Accepted publickey for alice",
    )

    assert _log_entry_key(entry) == _log_entry_key(entry)


def test_build_interactive_logs_section_generates_unique_keys_for_duplicate_entries() -> None:
    duplicate = LogEntry(
        timestamp=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        source="journal",
        unit="sshd.service",
        priority="info",
        message="Accepted publickey for alice",
    )
    state = SystemState(logs=LogsState(entries=[duplicate, duplicate]))

    widget = build_interactive_section(
        state,
        DetailViewState(section="Logs", sort_key="timestamp", sort_desc=True),
    )

    assert widget is not None
    assert len(widget.spec.rows) == 2
    assert len({row.key for row in widget.spec.rows}) == 2


def test_build_interactive_process_section_generates_unique_keys_for_duplicate_pids() -> None:
    state = SystemState(
        processes=ProcessesState(
            total_processes=2,
            entries=[
                ProcessEntry(pid=10, name="alpha", username="root", cpu_percent=12.0, memory_percent=1.0),
                ProcessEntry(pid=10, name="beta", username="alice", cpu_percent=88.0, memory_percent=4.0),
            ],
        )
    )

    widget = build_interactive_section(
        state,
        DetailViewState(section="Processes", sort_key="cpu", sort_desc=True),
    )

    assert widget is not None
    assert [row.key for row in widget.spec.rows] == ["10", "10-1"]
    assert [row.target for row in widget.spec.rows] == ["10", "10"]