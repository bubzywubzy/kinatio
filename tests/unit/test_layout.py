from rich.console import Console
from datetime import UTC, datetime

from kinatio.domain.models import (
    CPUInfo,
    DiskDevice,
    GPUInfo,
    GPUWorkloadInfo,
    OSState,
    AuditFinding,
    AuditState,
    CollectionAccessInfo,
    CollectorHealth,
    ContainerEntry,
    ContainersState,
    HardwareState,
    LoginHistoryEntry,
    LogEntry,
    LogsState,
    MemoryInfo,
    NetworkState,
    PackageEntry,
    PackagesState,
    PortEntry,
    PowerState,
    ProcessesState,
    RouteEntry,
    SecurityFinding,
    SecurityState,
    ServiceEntry,
    ServicesState,
    RuntimeContext,
    SessionEntry,
    SessionsState,
    SystemState,
    ThermalSensor,
)
from kinatio.ui.layout import (
    DEFERRED_SUBSYSTEMS,
    PRIVILEGED_SECTIONS,
    SECTIONS,
    format_brand_header,
    format_contextual_keybinds,
    format_locked_section,
    format_section_health_banner,
    format_startup_welcome,
    format_state_section,
    format_status_bar,
    get_section_policy,
)


def _segment_style_for_text(renderable: object, needle: str):
    console = Console(force_terminal=True, color_system="truecolor", width=140)
    fallback = None
    for segment in console.render(renderable):
        if segment.text.strip() == needle:
            return segment.style
        if fallback is None and needle in segment.text:
            fallback = segment.style
    if fallback is not None:
        return fallback
    raise AssertionError(f"missing segment containing {needle!r}")


def _render_plain_text(renderable: object, *, width: int = 140) -> str:
    console = Console(width=width)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_hardware_section_highlights_hot_metrics() -> None:
    state = SystemState(
        hardware=HardwareState(
            cpu=CPUInfo(logical_cores=16, physical_cores=8, load_percent=91.0, model_name="Unit Test CPU", architecture="x86_64"),
            memory=MemoryInfo(total_bytes=16 * 1024**3, used_bytes=15 * 1024**3, percent=93.0),
        )
    )

    renderable = format_state_section("Hardware", state)

    load_style = _segment_style_for_text(renderable, "91.0%")
    memory_style = _segment_style_for_text(renderable, "93.0%")

    assert load_style is not None and load_style.color is not None and load_style.color.name == "red"
    assert memory_style is not None and memory_style.color is not None and memory_style.color.name == "red"


def test_hardware_section_surfaces_cpu_metadata_and_inventory_sample() -> None:
    state = SystemState(
        hardware=HardwareState(
            cpu=CPUInfo(
                logical_cores=16,
                physical_cores=8,
                load_percent=32.5,
                model_name="Unit Test CPU",
                architecture="x86_64",
                frequency_current_mhz=2450.0,
                frequency_max_mhz=4800.0,
            ),
            pci_devices=[{"category": "lspci", "identifier": "0000:01:00.0", "description": "VGA controller"}],
            usb_devices=[{"category": "lsusb", "identifier": "Bus001", "description": "USB hub"}],
        )
    )

    rendered = _render_plain_text(format_state_section("Hardware", state)).lower()

    assert "unit test cpu" in rendered
    assert "x86_64" in rendered
    assert "vga controller" in rendered
    assert "usb hub" in rendered


def test_hardware_section_surfaces_gpu_thermal_and_disk_overview() -> None:
    state = SystemState(
        hardware=HardwareState(
            cpu=CPUInfo(
                logical_cores=16,
                physical_cores=8,
                load_percent=32.5,
                model_name="Unit Test CPU",
                architecture="x86_64",
            ),
            gpus=[
                GPUInfo(
                    name="NVIDIA GeForce RTX 3070",
                    vendor="NVIDIA",
                    driver="550.54",
                    bus_id="0000:01:00.0",
                    memory_total_bytes=8 * 1024**3,
                    memory_used_bytes=2 * 1024**3,
                    utilization_percent=35.0,
                    temperature_celsius=61.0,
                    workload_source="nvidia-smi",
                    workloads=[
                        GPUWorkloadInfo(
                            pid=4242,
                            process_name="python",
                            command="python train.py --epochs 3",
                            gpu_memory_bytes=1024 * 1024 * 1024,
                            kind="compute",
                        )
                    ],
                )
            ],
        ),
        power=PowerState(
            thermal_sensors=[
                ThermalSensor(source="acpitz", label="cpu package", current_celsius=63.0, high_celsius=95.0)
            ]
        ),
        storage={
            "disks": [
                DiskDevice(name="nvme0n1", model="Fast Disk", size_bytes=1024**4, smart_health="passed", temperature_celsius=46.0)
            ]
        },
    )

    rendered = _render_plain_text(format_state_section("Hardware", state)).lower()
    hardware_policy = get_section_policy("Hardware")

    assert "graphics" in rendered
    assert "nvidia geforce rtx 3070" in rendered
    assert "bus 0000:01:00.0" in rendered
    assert "2.0 gib / 8.0 gib" in rendered
    assert "running python[4242] 1.0 gib" in rendered
    assert "cmd python train.py --epochs 3" in rendered
    assert "cpu package" in rendered
    assert "63.0 °c" in rendered
    assert "46.0 °c" in rendered
    assert "storage devices" in rendered
    assert hardware_policy is not None and hardware_policy.description.lower() in rendered
    assert "power for the full sensor list" not in rendered


def test_hardware_section_reflows_dense_rows_for_static_panel_width() -> None:
    state = SystemState(
        hardware=HardwareState(
            cpu=CPUInfo(
                logical_cores=32,
                physical_cores=16,
                load_percent=48.3,
                model_name="Very Long Test CPU Model Name That Might Wrap Poorly",
                architecture="x86_64",
                frequency_current_mhz=2450.0,
                frequency_max_mhz=5150.0,
            ),
            memory=MemoryInfo(
                total_bytes=64 * 1024**3,
                used_bytes=31 * 1024**3,
                available_bytes=33 * 1024**3,
                percent=48.3,
                swap_total_bytes=8 * 1024**3,
                swap_used_bytes=2 * 1024**3,
                swap_percent=25.0,
            ),
            gpus=[
                GPUInfo(
                    name="NVIDIA GeForce RTX 4090 Founders Edition",
                    vendor="NVIDIA",
                    driver="550.54",
                    bus_id="0000:01:00.0",
                    memory_total_bytes=24 * 1024**3,
                    memory_used_bytes=6 * 1024**3,
                    utilization_percent=35.0,
                    temperature_celsius=61.0,
                    workload_source="nvidia-smi",
                    workloads=[
                        GPUWorkloadInfo(
                            pid=4242,
                            process_name="python",
                            command="python train.py --epochs 3 --batch-size 64 --mixed-precision",
                            gpu_memory_bytes=1024**3,
                            kind="compute",
                        )
                    ],
                ),
                GPUInfo(name="AMD Radeon Pro W6800", vendor="AMD", driver="amdgpu", bus_id="0000:07:00.0"),
            ],
        ),
        power=PowerState(
            thermal_sensors=[
                ThermalSensor(source="acpitz", label="cpu package", current_celsius=63.0, high_celsius=95.0)
            ]
        ),
        storage={
            "disks": [
                DiskDevice(
                    name="nvme0n1",
                    model="Ridiculously Fast NVMe Device With Long Marketing Name",
                    size_bytes=2 * 1024**4,
                    transport="nvme",
                    smart_health="passed",
                    temperature_celsius=46.0,
                )
            ]
        },
    )

    rendered = _render_plain_text(format_state_section("Hardware", state), width=96).lower()
    lines = [line.strip() for line in rendered.splitlines() if line.strip()]

    assert "cpu 32c / 16p  |  mem 48.3%" in lines
    assert any(line.startswith("gpu nvidia geforce rt") for line in lines)
    assert "thermals 63.0 °c  |  disk temp 46.0 °c" in lines
    assert any(line.startswith("model very long test cpu model") for line in lines)
    assert not any("gpu nvidia" in line and "thermals 63.0 °c" in line for line in lines)


def test_hardware_section_names_multiple_gpus_instead_of_only_reporting_a_count() -> None:
    state = SystemState(
        hardware=HardwareState(
            gpus=[
                GPUInfo(name="NVIDIA GeForce RTX 3070", vendor="NVIDIA"),
                GPUInfo(name="AMD Radeon RX 6800", vendor="AMD"),
                GPUInfo(name="Intel Arc A770", vendor="Intel"),
            ]
        )
    )

    rendered = _render_plain_text(format_state_section("Hardware", state)).lower().replace("\n", " ")

    assert "nvidia geforce rt" in rendered
    assert "amd radeon rx 6800" in rendered
    assert "+1 more" in rendered
    assert "3 present" not in rendered


def test_security_section_highlights_critical_findings() -> None:
    state = SystemState(
        security=SecurityState(
            findings=[
                SecurityFinding(
                    severity="critical",
                    title="Open SSH root login",
                    detail="PermitRootLogin is enabled",
                    path="/etc/ssh/sshd_config",
                )
            ]
        )
    )

    rendered = _render_plain_text(format_state_section("Security", state))

    assert "CRITICAL" in rendered
    assert "Open SSH root login" in rendered


def test_network_alias_now_maps_to_summary_view_without_ports_listing() -> None:
    state = SystemState(
        network=NetworkState(
            routes=[RouteEntry(destination="default", gateway="192.168.1.1", device="eth0")],
            dns={"servers": ["1.1.1.1"], "source": "resolv.conf"},
            listening_ports=[PortEntry(protocol="tcp", local_address="0.0.0.0", local_port=22, process_name="sshd")],
        )
    )

    rendered = _render_plain_text(format_state_section("Network", state)).lower()

    assert "default route via 192.168.1.1" in rendered
    assert "1.1.1.1" in rendered
    assert "sshd" not in rendered


def test_security_alias_now_maps_to_posture_view_without_identity_listing() -> None:
    state = SystemState(
        security=SecurityState(
            users=["alice", "bob"],
            groups={"wheel": ["alice"]},
            findings=[SecurityFinding(severity="critical", title="Open SSH root login", detail="PermitRootLogin is enabled")],
        )
    )

    rendered = _render_plain_text(format_state_section("Security", state)).lower()

    assert "open ssh root login" in rendered
    assert "alice" not in rendered
    assert "wheel" not in rendered


def test_services_section_highlights_failed_units() -> None:
    state = SystemState(
        services=ServicesState(
            services=[
                ServiceEntry(
                    name="sshd.service",
                    active_state="failed",
                    sub_state="failed",
                    is_failed=True,
                    is_enabled=True,
                )
            ]
        )
    )

    renderable = format_state_section("Services", state)

    service_style = _segment_style_for_text(renderable, "sshd.service")

    assert service_style is not None and service_style.color is not None and service_style.color.name == "red"


def test_status_bar_highlights_alert_count() -> None:
    state = SystemState(
        services=ServicesState(
            services=[
                ServiceEntry(
                    name="sshd.service",
                    active_state="failed",
                    sub_state="failed",
                    is_failed=True,
                )
            ]
        ),
        security=SecurityState(
            findings=[SecurityFinding(severity="critical", title="Bad sudoers", detail="NOPASSWD wildcard")]
        ),
        collector_health={"network": CollectorHealth(collector="network", status="error", error="timeout")},
    )

    renderable = format_status_bar("Services", state, auth_label="locked", auth_style="bold red")

    alert_style = _segment_style_for_text(renderable, "3")

    assert alert_style is not None and alert_style.color is not None and alert_style.color.name == "red"


def test_sections_expand_beyond_original_core_views() -> None:
    assert "Overview" in SECTIONS
    assert "Kernel" in SECTIONS
    assert "Containers" in SECTIONS


def test_section_policy_tracks_locked_and_deferred_categories() -> None:
    logs_policy = get_section_policy("Logs")
    network_policy = get_section_policy("Network")
    kernel_policy = get_section_policy("Kernel")

    assert logs_policy is not None and logs_policy.requires_auth is True
    assert logs_policy.collection_mode == "defer_until_unlock"
    assert "Logs" in PRIVILEGED_SECTIONS
    assert "logs" in DEFERRED_SUBSYSTEMS
    assert network_policy is not None and network_policy.requires_auth is False
    assert kernel_policy is not None and kernel_policy.subsystem == "os_state"


def test_system_section_surfaces_runtime_context() -> None:
    state = SystemState(
        runtime=RuntimeContext(
            distro_name="Arch Linux",
            distro_version="rolling",
            init_system="systemd",
            service_manager="systemd",
            log_backend="journalctl",
            package_manager="pacman",
            firewall_backend="nftables",
            security_backend="apparmor",
            container_runtime="podman",
        )
    )

    rendered = _render_plain_text(format_state_section("System", state)).lower()

    assert "arch linux" in rendered
    assert "journalctl" in rendered
    assert "pacman" in rendered
    assert "podman" in rendered


def test_system_health_view_stays_operational_and_defers_kernel_release_to_admin_views() -> None:
    state = SystemState(
        os_state=OSState(hostname="unit-host", fqdn="unit-host.local", kernel_release="6.12.0-unit", uptime_seconds=1234),
        runtime=RuntimeContext(distro_name="Arch Linux", init_system="systemd", service_manager="systemd"),
        hardware=HardwareState(
            cpu=CPUInfo(logical_cores=8, physical_cores=4, load_percent=42.0),
            memory=MemoryInfo(percent=68.0),
        ),
    )

    rendered = _render_plain_text(format_state_section("System Health", state)).lower()

    assert "unit-host" in rendered
    assert "arch linux" in rendered
    assert "1234 s" in rendered
    assert "6.12.0-unit" not in rendered


def test_routes_dns_view_focuses_on_routes_and_resolver_without_port_noise() -> None:
    state = SystemState(
        network=NetworkState(
            routes=[RouteEntry(destination="default", gateway="192.168.1.1", device="eth0", metric=100)],
            dns={"servers": ["1.1.1.1"], "search": ["lab.local"], "source": "resolv.conf"},
            listening_ports=[PortEntry(protocol="tcp", local_address="0.0.0.0", local_port=22, process_name="sshd")],
        )
    )

    rendered = _render_plain_text(format_state_section("Routes & DNS", state)).lower()

    assert "192.168.1.1" in rendered
    assert "1.1.1.1" in rendered
    assert "lab.local" in rendered
    assert "sshd" not in rendered


def test_firewall_view_surfaces_observe_only_backend_summary() -> None:
    state = SystemState(
        network=NetworkState(
            firewall={"backend": "nftables", "enabled": True, "summary": "policy drop on input"}
        )
    )

    rendered = _render_plain_text(format_state_section("Firewall", state)).lower()

    assert "nftables" in rendered
    assert "policy drop on input" in rendered
    assert "press x" not in rendered


def test_access_identity_view_surfaces_users_and_groups_without_finding_feed() -> None:
    state = SystemState(
        security=SecurityState(
            sudo_available=True,
            sudo_configured=True,
            users=["alice", "bob"],
            groups={"wheel": ["alice"], "dev": ["alice", "bob"]},
            findings=[SecurityFinding(severity="critical", title="Root login", detail="enabled")],
        )
    )

    rendered = _render_plain_text(format_state_section("Access & Identity", state)).lower()

    assert "alice" in rendered
    assert "wheel" in rendered
    assert "root login" not in rendered


def test_runtime_backends_view_surfaces_backend_status_inventory() -> None:
    state = SystemState(
        runtime=RuntimeContext(
            distro_name="Arch Linux",
            init_system="systemd",
            service_manager="systemd",
            log_backend="journalctl",
            package_manager="pacman",
            firewall_backend="nftables",
            security_backend="apparmor",
            container_runtime="podman",
        ),
        backend_status={
            "logs": {"available": True},
            "firewall": {"available": False, "reason": "nft command missing"},
        },
    )

    rendered = _render_plain_text(format_state_section("Runtime Backends", state)).lower()

    assert "journalctl" in rendered
    assert "pacman" in rendered
    assert "podman" in rendered
    assert "nft command missing" in rendered


def test_overview_section_stays_summary_focused_without_runtime_backend_duplication() -> None:
    state = SystemState(
        os_state=OSState(hostname="unit-host", kernel_release="6.12.0-unit"),
        runtime=RuntimeContext(
            distro_name="Arch Linux",
            init_system="systemd",
            log_backend="journalctl",
            package_manager="pacman",
        ),
    )

    rendered = _render_plain_text(format_state_section("Overview", state)).lower()

    assert "unit-host" in rendered
    assert "arch linux" in rendered
    assert "6.12.0-unit" not in rendered
    assert "journalctl" not in rendered
    assert "systemd" not in rendered


def test_system_section_defers_kernel_release_and_version_to_kernel_view() -> None:
    state = SystemState(
        os_state=OSState(
            hostname="unit-host",
            fqdn="unit-host.local",
            kernel_release="6.12.0-unit",
            kernel_version="#1 unit build",
            uptime_seconds=1234,
        ),
        runtime=RuntimeContext(distro_name="Arch Linux", init_system="systemd"),
    )

    rendered = _render_plain_text(format_state_section("System", state)).lower()

    assert "unit-host" in rendered
    assert "arch linux" in rendered
    assert "6.12.0-unit" not in rendered
    assert "#1 unit build" not in rendered


def test_system_section_displays_uptime_in_seconds_with_explicit_unit() -> None:
    state = SystemState(os_state=OSState(uptime_seconds=1234))

    rendered = _render_plain_text(format_state_section("System", state)).lower()

    assert "uptime 1234 s" in rendered.replace("\n", " ")


def test_power_section_displays_temperature_in_celsius() -> None:
    state = SystemState(
        power=PowerState(
            battery_present=True,
            thermal_sensors=[ThermalSensor(source="acpitz", label="cpu", current_celsius=61.0)],
        )
    )

    rendered = _render_plain_text(format_state_section("Power", state))
    power_policy = get_section_policy("Power")

    assert "61.0 °c" in rendered.lower()
    assert power_policy is not None and power_policy.description.lower() in rendered.lower()
    assert "hardware keeps the at-a-glance physical overview" not in rendered.lower()


def test_hardware_section_omits_host_and_kernel_identity_details() -> None:
    state = SystemState(
        hardware=HardwareState(
            cpu=CPUInfo(logical_cores=8, physical_cores=4, load_percent=32.5, model_name="Unit Test CPU", architecture="x86_64"),
        ),
        os_state=OSState(hostname="unit-host", kernel_release="6.12.0-unit"),
    )

    rendered = _render_plain_text(format_state_section("Hardware", state)).lower()

    assert "unit test cpu" in rendered
    assert "unit-host" not in rendered
    assert "6.12.0-unit" not in rendered


def test_storage_section_surfaces_disk_temperature_when_available() -> None:
    state = SystemState(
        storage={
            "disks": [
                DiskDevice(name="nvme0n1", model="Fast Disk", transport="nvme", smart_health="passed", temperature_celsius=46.0)
            ]
        }
    )

    rendered = _render_plain_text(format_state_section("Storage", state)).lower()
    storage_policy = get_section_policy("Storage")

    assert "46.0 °c" in rendered
    assert storage_policy is not None and storage_policy.description.lower() in rendered
    assert "hardware shows the physical overview" not in rendered


def test_locked_section_prompts_for_unlock() -> None:
    renderable = format_locked_section("Security", "locked", "sudo credentials are required")

    lock_style = _segment_style_for_text(renderable, "SECURITY LOCKED")
    unlock_style = _segment_style_for_text(renderable, "Press U to unlock this session for privileged categories.")
    rendered = _render_plain_text(renderable)

    assert lock_style is not None and lock_style.color is not None and lock_style.color.name == "red"
    assert unlock_style is not None and unlock_style.color is not None and unlock_style.color.name == "grey70"
    assert "collection is deferred until unlock" in rendered.lower()
    assert "supports `--unlock`" in rendered


def test_status_bar_surfaces_deferred_collectors_without_counting_them_as_errors() -> None:
    state = SystemState(
        collector_health={
            "logs": CollectorHealth(
                collector="logs",
                status="idle",
                availability={
                    "available": False,
                    "reason": "Collection deferred until sudo authentication is unlocked.",
                    "dependency": "sudo",
                },
            )
        }
    )

    renderable = format_status_bar("Logs", state, auth_label="locked", auth_style="bold red")
    rendered = _render_plain_text(renderable).lower()

    assert "deferred" in rendered
    assert "errors 0" in rendered.replace("\n", " ")


def test_status_bar_hides_locked_section_snapshot_summary() -> None:
    state = SystemState(
        logs=LogsState(entries=[LogEntry(unit="sshd.service", message="cached privileged log line")])
    )

    rendered = _render_plain_text(
        format_status_bar(
            "Logs",
            state,
            auth_label="locked",
            auth_style="bold red",
            section_locked=True,
        )
    ).lower()

    assert "entries 1" not in rendered.replace("\n", " ")
    assert "latest" not in rendered


def test_status_bar_keeps_last_successful_collectors_in_ok_count_while_running() -> None:
    state = SystemState(
        collector_health={
            "hardware": CollectorHealth(
                collector="hardware",
                status="running",
                last_completed_status="ok",
            ),
            "network": CollectorHealth(
                collector="network",
                status="running",
                last_completed_status="error",
                error="timed out",
            ),
        }
    )

    rendered = _render_plain_text(
        format_status_bar("Hardware", state, auth_label="authenticated", auth_style="bold white")
    ).lower()

    assert "ok 1" in rendered.replace("\n", " ")
    assert "running 2" in rendered.replace("\n", " ")
    assert "errors 1" in rendered.replace("\n", " ")


def test_status_bar_uses_selected_section_timestamp_instead_of_global_state_timestamp() -> None:
    state = SystemState(
        timestamp=datetime(2026, 5, 15, 12, 30, tzinfo=UTC),
        processes=ProcessesState(refreshed_at=datetime(2026, 5, 15, 12, 0, tzinfo=UTC)),
        logs=LogsState(refreshed_at=datetime(2026, 5, 15, 12, 20, tzinfo=UTC)),
    )

    rendered = _render_plain_text(
        format_status_bar("Processes", state, auth_label="authenticated", auth_style="bold white")
    )

    assert "2026-05-15T12:00:00+00:00" in rendered
    assert "2026-05-15T12:30:00+00:00" not in rendered


def test_status_bar_can_render_interaction_hint_line() -> None:
    renderable = format_status_bar(
        "Logs",
        SystemState(),
        auth_label="authenticated",
        auth_style="bold white",
        interaction_hint="Enter detail · F follow newest",
    )

    rendered = _render_plain_text(renderable)

    assert "HINT" in rendered
    assert "follow newest" in rendered


def test_status_bar_surfaces_section_specific_snapshot_summary() -> None:
    state = SystemState(
        services=ServicesState(
            manager="systemd",
            services=[
                ServiceEntry(name="sshd.service", active_state="active", sub_state="running", is_enabled=True),
                ServiceEntry(name="cron.service", active_state="failed", sub_state="failed", is_failed=True),
            ],
        )
    )

    rendered = _render_plain_text(
        format_status_bar("Services", state, auth_label="authenticated", auth_style="bold white")
    ).lower()

    assert "manager systemd" in rendered.replace("\n", " ")
    assert "active 1" in rendered.replace("\n", " ")
    assert "failed 1" in rendered.replace("\n", " ")


def test_security_status_bar_snapshot_uses_bounded_sudo_status_instead_of_raw_policy_text() -> None:
    raw_summary = "matching defaults entries for alice on host: env_reset, mail_badpass"
    state = SystemState(
        security=SecurityState(
            sudo_available=True,
            sudo_authenticated=False,
            sudo_non_interactive=False,
            sudo_summary=raw_summary,
        )
    )

    rendered = _render_plain_text(
        format_status_bar("Security Posture", state, auth_label="locked", auth_style="bold red")
    ).lower()

    assert raw_summary.lower() not in rendered
    assert "sudo locked" in rendered.replace("\n", " ")


def test_security_posture_moves_bounded_sudo_summary_into_body_area() -> None:
    raw_summary = "matching defaults entries for alice on host: env_reset, mail_badpass, secure_path=/usr/bin"
    state = SystemState(
        security=SecurityState(
            sudo_available=True,
            sudo_non_interactive=True,
            sudo_configured=True,
            sudo_summary=raw_summary,
        )
    )

    rendered = _render_plain_text(format_state_section("Security Posture", state)).lower()

    assert "sudo non-interactive" in rendered.replace("\n", " ")
    assert "sudo policy" in rendered
    assert raw_summary.lower() in rendered


def test_contextual_keybind_bar_formats_compact_key_action_pairs() -> None:
    rendered = _render_plain_text(
        format_contextual_keybinds((("↑↓", "move"), ("Enter", "open"), ("Q", "quit")))
    )

    normalized = rendered.replace("\n", " ")

    assert "↑↓ move" in normalized
    assert "Enter open" in normalized
    assert "Q quit" in normalized


def test_brand_header_uses_ascii_logo_when_terminal_is_wide_enough() -> None:
    rendered = _render_plain_text(
        format_brand_header(
            width=120,
            selected_category="Operations",
            selected_section="Processes",
            auth_label="authenticated",
            auth_style="bold white",
            context_hint="interactive list ready · Enter detail · / filter",
            hostname="unit-host",
            alert_count=2,
        )
    )

    assert "██╗  ██╗██╗███╗   ██╗" in rendered
    assert "operations › processes" in rendered.lower()
    assert "host unit-host" in rendered.lower()
    assert "alerts 2" in rendered.lower()
    assert "interactive list ready" in rendered.lower()


def test_brand_header_falls_back_to_compact_title_on_narrow_widths() -> None:
    rendered = _render_plain_text(
        format_brand_header(
            width=48,
            selected_section="Overview",
            auth_label="locked",
            auth_style="bold red",
            context_hint="browse sections with ↑↓ · Tab focus · R refresh",
            hostname="unit-host",
            alert_count=1,
        )
    )

    assert "kinatio" in rendered.lower()
    assert "host unit-host" in rendered.lower()
    assert "focus overview" in rendered.lower()
    assert "alerts 1" in rendered.lower()
    assert "██╗  ██╗██╗███╗   ██╗" not in rendered


def test_brand_header_renders_ascii_logo_by_line_instead_of_single_glyph_column() -> None:
    rendered = _render_plain_text(
        format_brand_header(
            width=120,
            selected_section="Overview",
            auth_label="authenticated",
            auth_style="bold white",
            context_hint="browse sections with ↑↓ · Tab focus · R refresh",
            hostname="unit-host",
        )
    )

    non_empty_lines = [line.strip() for line in rendered.splitlines() if line.strip()]

    assert any(line.startswith("██╗  ██╗██╗") for line in non_empty_lines)
    assert any("Keeping penguins professionally over-informed." in line for line in non_empty_lines)


def test_brand_header_supports_compact_startup_mode() -> None:
    rendered = _render_plain_text(
        format_brand_header(
            width=120,
            selected_section="Overview",
            auth_label="locked",
            auth_style="bold red",
            context_hint="Choose a category to begin · Enter opens sections · R refresh",
            hostname="unit-host",
            compact=True,
            focus_label="categories",
        )
    )

    normalized = rendered.lower().replace("\n", " ")

    assert "██╗  ██╗██╗███╗   ██╗" in rendered
    assert "focus categories" in normalized
    assert "choose a category to begin" in normalized
    assert "keeping penguins professionally over-informed" in normalized


def test_startup_welcome_guides_category_first_launch() -> None:
    rendered = _render_plain_text(
        format_startup_welcome(
            selected_category="Overview",
            state=SystemState(
                os_state=OSState(hostname="unit-host"),
                hardware=HardwareState(
                    cpu=CPUInfo(load_percent=42.0),
                    memory=MemoryInfo(percent=68.0),
                ),
            ),
        )
    ).lower()
    normalized = rendered.replace("\n", " ")

    assert "control deck ready" in normalized
    assert "selected lane overview" in normalized
    assert "press enter to open this category" in normalized
    assert "host unit-host" in normalized


def test_section_health_banner_surfaces_deferred_collection_state() -> None:
    renderable = format_section_health_banner(
        "Logs",
        CollectorHealth(
            collector="logs",
            status="idle",
            availability={
                "available": False,
                "reason": "Collection deferred until sudo authentication is unlocked.",
                "dependency": "sudo",
            },
        ),
    )

    rendered = _render_plain_text(renderable)

    assert renderable is not None
    assert "COLLECTION DEFERRED" in rendered
    assert "Unlock sudo" in rendered


def test_section_health_banner_marks_failed_collectors_as_stale() -> None:
    renderable = format_section_health_banner(
        "Services",
        CollectorHealth(
            collector="services",
            status="error",
            error="systemctl timed out",
        ),
    )

    rendered = _render_plain_text(renderable)

    assert renderable is not None
    assert "DATA MAY BE STALE" in rendered
    assert "systemctl timed out" in rendered


def test_section_health_banner_omits_transient_running_state() -> None:
    renderable = format_section_health_banner(
        "Processes",
        CollectorHealth(
            collector="processes",
            status="running",
            last_completed_status="ok",
        ),
    )

    assert renderable is None


def test_new_sections_render_real_data_without_scaffold_copy() -> None:
    state = SystemState(
        sessions=SessionsState(
            current_sessions=[SessionEntry(username="alice", terminal="pts/0", host="10.0.0.4")],
            recent_logins=[LoginHistoryEntry(username="alice", terminal="pts/0", summary="alice pts/0 10.0.0.4 2026-05-13T08:00:00+00:00 still logged in")],
        ),
        power=PowerState(
            battery_present=True,
            battery_percent=82.5,
            power_plugged=False,
            thermal_sensors=[ThermalSensor(source="acpitz", label="cpu", current_celsius=61.0)],
            cpu_governors={"powersave": 8},
        ),
        packages=PackagesState(
            manager="dpkg",
            installed_count=1200,
            update_count=4,
            entries=[PackageEntry(name="bash", version="5.2", architecture="amd64", update_version="5.3")],
        ),
        audit=AuditState(
            selinux_enabled=True,
            selinux_mode="enforcing",
            apparmor_enabled=False,
            auditd_active=True,
            findings=[AuditFinding(severity="info", title="Backends healthy", detail="No immediate posture warnings")],
        ),
        containers=ContainersState(
            runtime="docker",
            running_count=1,
            total_count=2,
            image_count=5,
            containers=[ContainerEntry(container_id="abc123", name="web", image="nginx:stable", state="running", status="Up 2 hours", ports="0.0.0.0:80->80/tcp")],
        ),
    )

    rendered = "\n".join(
        [
            _render_plain_text(format_state_section("Sessions", state)),
            _render_plain_text(format_state_section("Power", state)),
            _render_plain_text(format_state_section("Packages", state)),
            _render_plain_text(format_state_section("Audit", state)),
            _render_plain_text(format_state_section("Containers", state)),
        ]
    )

    normalized = rendered.lower()

    assert "collector pending" not in normalized
    assert "planned next" not in normalized
    assert "alice" in normalized
    assert "82.5%" in normalized
    assert "bash" in normalized
    assert "backends healthy" in normalized
    assert "nginx:stable" in normalized


def test_overview_section_surfaces_cross_section_operational_counts() -> None:
    state = SystemState(
        packages=PackagesState(update_count=7),
        containers=ContainersState(running_count=2, total_count=3),
        sessions=SessionsState(current_sessions=[SessionEntry(username="alice"), SessionEntry(username="bob")]),
        audit=AuditState(findings=[AuditFinding(severity="warning", title="auditd inactive", detail="..." )]),
    )

    rendered = _render_plain_text(format_state_section("Overview", state)).lower()

    assert "pkg upd 7" in rendered.replace("\n", " ")
    assert "ctr run 2/3" in rendered.replace("\n", " ")
    assert "sessions 2" in rendered.replace("\n", " ")
    assert "audit 1" in rendered.replace("\n", " ")


def test_packages_section_omits_arch_placeholder_for_manager_without_arch_data() -> None:
    state = SystemState(
        packages=PackagesState(
            manager="pacman",
            installed_count=2,
            update_count=1,
            entries=[
                PackageEntry(name="bash", version="5.2.037-5", update_version="5.2.037-6", summary="The GNU Bourne Again shell"),
                PackageEntry(name="vim", version="9.1.001-1"),
            ],
        )
    )

    rendered = _render_plain_text(format_state_section("Packages", state)).lower()

    assert "arch n/a" not in rendered
    assert "status update -> 5.2.037-6" in rendered.replace("\n", " ")
    assert "the gnu bourne again shell" in rendered


def test_audit_section_surfaces_auditctl_detail_metrics() -> None:
    state = SystemState(
        audit=AuditState(
            audit_status="enabled 1",
            audit_details={"enabled": "1", "failure": "1", "backlog_limit": "8192", "backlog": "0"},
        )
    )

    rendered = _render_plain_text(format_state_section("Audit", state)).lower()

    assert "backlog limit 8192" in rendered.replace("\n", " ")
    assert "failure 1" in rendered.replace("\n", " ")


def test_containers_section_surfaces_short_id_and_ports() -> None:
    state = SystemState(
        containers=ContainersState(
            runtime="docker",
            running_count=1,
            total_count=1,
            image_count=1,
            containers=[
                ContainerEntry(
                    container_id="abc123def456",
                    name="web",
                    image="nginx:stable",
                    state="running",
                    status="Up 2 hours",
                    ports="0.0.0.0:80->80/tcp",
                )
            ],
        )
    )

    rendered = _render_plain_text(format_state_section("Containers", state)).lower()

    assert "abc123def456"[:12] in rendered
    assert "0.0.0.0:80->80/tcp" in rendered


def test_logs_section_surfaces_elevated_access_metadata() -> None:
    state = SystemState(
        logs=LogsState(
            collection_access=CollectionAccessInfo(
                requires_auth=True,
                elevated=True,
                detail="Collected journal history through the cached sudo session.",
            )
        )
    )

    rendered = _render_plain_text(format_state_section("Logs", state)).lower()

    assert "access elevated" in rendered.replace("\n", " ")
    assert "cached sudo session" in rendered


def test_audit_section_surfaces_partial_access_metadata() -> None:
    state = SystemState(
        audit=AuditState(
            collection_access=CollectionAccessInfo(
                requires_auth=True,
                partial=True,
                detail="auditctl requires elevated privileges for full status on this host.",
            )
        )
    )

    rendered = _render_plain_text(format_state_section("Audit", state)).lower()

    assert "access partial" in rendered.replace("\n", " ")
    assert "requires elevated privileges" in rendered