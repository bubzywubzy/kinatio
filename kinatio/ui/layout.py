"""UI layout helpers."""

from __future__ import annotations

from datetime import datetime

from rich.align import Align
from rich.console import Group, RenderableType
from rich.text import Text

from kinatio.domain.models import CollectorHealth, DiskDevice, GPUInfo, SystemState, ThermalSensor
from kinatio.sections import DEFERRED_SUBSYSTEMS, PRIVILEGED_SECTIONS, SECTIONS, get_category_policy, get_section_policy, section_updated_at

__all__ = [
    "DEFERRED_SUBSYSTEMS",
    "PRIVILEGED_SECTIONS",
    "SECTIONS",
    "format_brand_header",
    "format_contextual_keybinds",
    "format_locked_section",
    "format_section_health_banner",
    "format_startup_welcome",
    "format_state_section",
    "format_status_bar",
    "get_section_policy",
]


_ASCII_BRAND = (
    "██╗  ██╗██╗███╗   ██╗ █████╗ ████████╗██╗ ██████╗ ",
    "██║ ██╔╝██║████╗  ██║██╔══██╗╚══██╔══╝██║██╔═══██╗",
    "█████╔╝ ██║██╔██╗ ██║███████║   ██║   ██║██║   ██║",
    "██╔═██╗ ██║██║╚██╗██║██╔══██║   ██║   ██║██║   ██║",
    "██║  ██╗██║██║ ╚████║██║  ██║   ██║   ██║╚██████╔╝",
    "╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝   ╚═╝   ╚═╝ ╚═════╝ ",
)


def _bytes_to_text(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def _mhz_to_text(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0f} MHz"


def _mbps_to_text(value: int | None, *, unavailable: str = "n/a") -> str:
    if value is None:
        return unavailable
    return f"{value} Mb/s"


def _seconds_to_text(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    return f"{int(value)} s"


def _celsius_to_text(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f} °C"


def _percent_text(value: float | None, *, unavailable: str = "n/a") -> str:
    if value is None:
        return unavailable
    return f"{value:.1f}%"


def _timestamp_text(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _truncate_text(value: str, *, max_length: int = 28) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 1]}…"


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _bounded_detail_text(value: str | None, *, max_length: int = 180) -> str | None:
    if not value:
        return None
    collapsed = _collapse_whitespace(value)
    if not collapsed:
        return None
    return _truncate_text(collapsed, max_length=max_length)


def _header(title: str, refreshed_at: datetime) -> list[Text]:
    return [
        Text(title.upper(), style="bold white", justify="center"),
        Text.assemble(("updated ", "dim"), (_timestamp_text(refreshed_at), "grey62"), justify="center"),
        Text(),
    ]


def _section_header(title: str, refreshed_at: datetime) -> list[Text]:
    lines = _header(title, refreshed_at)
    policy = get_section_policy(title)
    if policy is None or not policy.description:
        return lines
    lines.extend([
        _subheading("Summary"),
        Text(policy.description, style="grey62", justify="center"),
        Text(),
    ])
    return lines


def _subheading(title: str) -> Text:
    return Text(title.upper(), style="bold grey70", justify="center")


def _metric(label: str, value: str, *, style: str = "white") -> Text:
    return Text.assemble((label.upper(), "grey50"), (" ", "grey50"), (value, style))


def _metric_row(*metrics: Text) -> Text:
    row = Text(justify="center")
    for index, metric in enumerate(metrics):
        if index:
            row.append("  |  ", style="grey35")
        row.append_text(metric)
    return row


def _centered(renderable: RenderableType) -> RenderableType:
    return Align.center(renderable, vertical="top")


def format_brand_header(
    *,
    width: int,
    selected_section: str,
    auth_label: str,
    auth_style: str,
    context_hint: str,
    hostname: str | None = None,
    alert_count: int = 0,
    selected_category: str | None = None,
    show_ascii: bool = True,
    ascii_min_width: int = 72,
    compact: bool = False,
    focus_label: str | None = None,
) -> RenderableType:
    section_label = (
        focus_label
        if focus_label is not None
        else (
            selected_section
            if selected_category is None or selected_category == selected_section
            else f"{selected_category} › {selected_section}"
        )
    )
    host_value = hostname or "host n/a"
    alert_style = "bold red" if alert_count else "grey62"
    render_ascii = show_ascii and width >= ascii_min_width
    lines: list[Text] = []

    if render_ascii:
        for line in _ASCII_BRAND:
            lines.append(Text(line, style="bold white", justify="center"))
    else:
        lines.append(Text("KINATIO", style="bold white", justify="center"))

    lines.extend([
        Text("Keeping penguins professionally over-informed.", style="grey62", justify="center"),
        Text.assemble(
            ("host ", "grey50"),
            (host_value, "white"),
            ("  ·  ", "grey35"),
            ("focus ", "grey50"),
            (section_label, "white"),
            ("  ·  ", "grey35"),
            ("auth ", "grey50"),
            (auth_label, auth_style),
            ("  ·  ", "grey35"),
            ("alerts ", "grey50"),
            (str(alert_count), alert_style),
            justify="center",
        ),
    ])

    if compact:
        lines.append(Text(context_hint, style="grey70", justify="center"))
        return _centered(Group(*lines))

    if render_ascii:
        lines.append(Text("linux system control deck", style="grey50", justify="center"))
    lines.append(Text(context_hint, style="grey70", justify="center"))
    return _centered(Group(*lines))


def format_startup_welcome(*, selected_category: str, state: SystemState) -> RenderableType:
    category_policy = get_category_policy(selected_category)
    critical_findings = sum(1 for finding in state.security.findings if finding.severity == "critical")
    failed_services = sum(1 for service in state.services.services if service.is_failed)
    hostname = state.os_state.hostname or "host n/a"
    lines = [
        Text("CONTROL DECK READY", style="bold white", justify="center"),
        Text(
            "Choose a lane, keep the rails quiet, and let the center canvas do the talking.",
            style="grey70",
            justify="center",
        ),
        Text(),
        _metric_row(
            _metric("Host", hostname, style="white"),
            _metric("Load", f"{state.hardware.cpu.load_percent:.1f}%", style=_threshold_style(state.hardware.cpu.load_percent, warning=65.0, critical=85.0)),
            _metric("Mem", f"{state.hardware.memory.percent:.1f}%", style=_threshold_style(state.hardware.memory.percent, warning=75.0, critical=90.0)),
            _metric("Alerts", str(critical_findings + failed_services), style="bold red" if (critical_findings + failed_services) else "white"),
        ),
        Text(),
        Text.assemble(
            ("selected lane ", "grey50"),
            (selected_category, "white"),
            ("  ·  ", "grey35"),
            ("ready ", "grey50"),
            ("press Enter to open this category", "grey70"),
            justify="center",
        ),
        Text(category_policy.description if category_policy is not None else "Choose the category that matches the question you want this host to answer first.", style="grey62", justify="center"),
        Text(),
        Text("Use ↑↓ to move through categories. Enter opens the selected lane. The side rails stay lean so the main panel can stay useful.", style="grey70", justify="center"),
    ]
    return _centered(Group(*lines))


def format_contextual_keybinds(bindings: tuple[tuple[str, str], ...]) -> Text:
    row = Text(justify="center")
    for index, (key, label) in enumerate(bindings):
        if index:
            row.append("  ·  ", style="grey35")
        row.append(key.upper() if len(key) == 1 else key, style="bold white")
        row.append(" ", style="grey50")
        row.append(label, style="grey70")
    return row


def _collection_access_label(*, elevated: bool, partial: bool) -> tuple[str, str]:
    if elevated:
        return "elevated", "bold white"
    if partial:
        return "partial", "bold white"
    return "standard", "grey62"


def _security_access_label(state: SystemState) -> tuple[str, str]:
    if state.security.collection_access.elevated:
        return "elevated", "bold white"
    if state.security.collection_access.partial:
        return "partial", "bold white"
    return "bounded", "grey70"


def _security_sudo_status(state: SystemState) -> tuple[str, str]:
    if state.security.sudo_available in {None, False}:
        return "unavailable", "grey62"
    if state.security.sudo_non_interactive:
        return "non-interactive", "bold white"
    if state.security.sudo_authenticated:
        return "unlocked", "bold white"
    if state.security.collection_access.partial:
        return "bounded", "grey70"
    return "locked", "bold red"


def _threshold_style(value: float, *, warning: float, critical: float) -> str:
    if value >= critical:
        return "bold red"
    if value >= warning:
        return "bold white"
    return "white"


def _severity_style(severity: str) -> str:
    if severity == "critical":
        return "bold red"
    if severity == "warning":
        return "bold white"
    return "grey62"


def _event_style(severity: str) -> str:
    if severity == "error":
        return "bold red"
    if severity == "warning":
        return "bold white"
    return "grey62"


def _service_style(is_failed: bool, active_state: str) -> str:
    if is_failed or active_state == "failed":
        return "bold red"
    if active_state == "active":
        return "white"
    return "grey62"


def _availability_style(available: bool) -> str:
    return "white" if available else "bold red"


def _temperature_style(value: float | None, *, warning: float, critical: float) -> str:
    if value is None:
        return "grey62"
    return _threshold_style(value, warning=warning, critical=critical)


def _gpu_memory_text(gpu: GPUInfo) -> str:
    if gpu.memory_total_bytes is None:
        return "n/a"
    if gpu.memory_used_bytes is None:
        return _bytes_to_text(gpu.memory_total_bytes)
    return f"{_bytes_to_text(gpu.memory_used_bytes)} / {_bytes_to_text(gpu.memory_total_bytes)}"


def _gpu_identity_text(gpu: GPUInfo, *, max_length: int = 32) -> str:
    name = _collapse_whitespace(gpu.name or "GPU")
    vendor = _collapse_whitespace(gpu.vendor or "")
    if vendor and not name.casefold().startswith(vendor.casefold()):
        name = f"{vendor} {name}"
    return _truncate_text(name, max_length=max_length)


def _gpu_workload_count_text(gpu: GPUInfo) -> str:
    if gpu.workloads:
        return f"{len(gpu.workloads)} active"
    if gpu.workload_source:
        return "sampled"
    return "n/a"


def _gpu_workload_summary_text(gpu: GPUInfo, *, max_items: int = 3) -> str | None:
    if not gpu.workloads:
        return None
    parts: list[str] = []
    for workload in gpu.workloads[:max_items]:
        pid_suffix = f"[{workload.pid}]" if workload.pid is not None else ""
        memory_suffix = f" {_bytes_to_text(workload.gpu_memory_bytes)}" if workload.gpu_memory_bytes is not None else ""
        parts.append(f"{workload.process_name}{pid_suffix}{memory_suffix}")
    if len(gpu.workloads) > max_items:
        parts.append(f"+{len(gpu.workloads) - max_items} more")
    return ", ".join(parts)


def _gpu_summary_text(state: SystemState) -> str:
    if not state.hardware.gpus:
        return "none"
    summary_parts: list[str] = []
    for gpu in state.hardware.gpus[:2]:
        label = _gpu_identity_text(gpu, max_length=18)
        if gpu.workloads:
            label = f"{label} ({len(gpu.workloads)} active)"
        summary_parts.append(label)
    if len(state.hardware.gpus) > 2:
        summary_parts.append(f"+{len(state.hardware.gpus) - 2} more")
    return " · ".join(summary_parts)


def _hottest_thermal_sensor(state: SystemState) -> ThermalSensor | None:
    sensors = state.power.thermal_sensors
    if not sensors:
        return None
    return max(sensors, key=lambda sensor: sensor.current_celsius)


def _hottest_disk(state: SystemState) -> DiskDevice | None:
    disks = [disk for disk in state.storage.disks if disk.temperature_celsius is not None]
    if not disks:
        return None
    return max(disks, key=lambda disk: disk.temperature_celsius or float("-inf"))


def _status_updated_at(selected_section: str, state: SystemState) -> datetime:
    return section_updated_at(selected_section, state)


def _bool_text(value: bool | None, *, true_text: str = "yes", false_text: str = "no") -> str:
    if value is None:
        return "n/a"
    return true_text if value else false_text


def _runtime_distro_label(state: SystemState) -> str:
    return state.runtime.distro_name or state.runtime.distro_id or "n/a"


def _firewall_state_text(state: SystemState, *, enabled_words: tuple[str, str] = ("on", "off")) -> str:
    firewall_value = state.network.firewall.backend or "none"
    if state.network.firewall.enabled is not None:
        firewall_value = f"{firewall_value} {enabled_words[0] if state.network.firewall.enabled else enabled_words[1]}"
    return firewall_value


def _connection_summary_text(connection: object) -> str:
    remote_address = getattr(connection, "remote_address", None) or "-"
    remote_port = getattr(connection, "remote_port", None)
    remote = remote_address if remote_port is None else f"{remote_address}:{remote_port}"
    return f"{getattr(connection, 'local_address', '-') }:{getattr(connection, 'local_port', '-')} → {remote}"


def _status_snapshot_line(selected_section: str, state: SystemState) -> Text | None:
    if selected_section == "Overview":
        return _metric_row(
            _metric("load", f"{state.hardware.cpu.load_percent:.1f}%", style=_threshold_style(state.hardware.cpu.load_percent, warning=65.0, critical=85.0)),
            _metric("mem", f"{state.hardware.memory.percent:.1f}%", style=_threshold_style(state.hardware.memory.percent, warning=75.0, critical=90.0)),
            _metric("pkg", str(state.packages.update_count) if state.packages.update_count is not None else "n/a"),
            _metric("ctr", f"{state.containers.running_count}/{state.containers.total_count}"),
        )
    if selected_section == "System":
        return _metric_row(
            _metric("distro", _runtime_distro_label(state), style="grey70"),
            _metric("init", state.runtime.init_system or "n/a"),
            _metric("svc", state.runtime.service_manager or "n/a"),
            _metric("log", state.runtime.log_backend or "n/a"),
        )
    if selected_section == "System Health":
        return _metric_row(
            _metric("host", state.os_state.hostname or "n/a", style="grey70"),
            _metric("load", f"{state.hardware.cpu.load_percent:.1f}%", style=_threshold_style(state.hardware.cpu.load_percent, warning=65.0, critical=85.0)),
            _metric("mem", f"{state.hardware.memory.percent:.1f}%", style=_threshold_style(state.hardware.memory.percent, warning=75.0, critical=90.0)),
            _metric("uptime", _seconds_to_text(state.os_state.uptime_seconds), style="grey70"),
        )
    if selected_section == "Hardware":
        hottest_thermal = _hottest_thermal_sensor(state)
        hottest_disk = _hottest_disk(state)
        disk_value = (
            _celsius_to_text(hottest_disk.temperature_celsius)
            if hottest_disk is not None and hottest_disk.temperature_celsius is not None
            else f"{len(state.storage.disks)} dev"
        )
        return _metric_row(
            _metric("cpu", _truncate_text(state.hardware.cpu.model_name or "n/a", max_length=22), style="grey70"),
            _metric("gpu", _truncate_text(_gpu_summary_text(state), max_length=22), style="grey70" if state.hardware.gpus else "grey62"),
            _metric(
                "thermals",
                _celsius_to_text(hottest_thermal.current_celsius) if hottest_thermal is not None else "n/a",
                style=_temperature_style(hottest_thermal.current_celsius if hottest_thermal is not None else None, warning=70.0, critical=85.0),
            ),
            _metric(
                "disk",
                disk_value,
                style=_temperature_style(hottest_disk.temperature_celsius if hottest_disk is not None else None, warning=50.0, critical=60.0) if hottest_disk is not None else "grey70",
            ),
        )
    if selected_section == "Performance":
        top_process = state.processes.entries[0].name if state.processes.entries else "n/a"
        return _metric_row(
            _metric("top", _truncate_text(top_process, max_length=18), style="grey70"),
            _metric("cpu", f"{state.hardware.cpu.load_percent:.1f}%", style=_threshold_style(state.hardware.cpu.load_percent, warning=65.0, critical=85.0)),
            _metric("load1", f"{state.os_state.load_average[0]:.2f}", style="grey70"),
            _metric("mem", f"{state.hardware.memory.percent:.1f}%", style=_threshold_style(state.hardware.memory.percent, warning=75.0, critical=90.0)),
        )
    if selected_section in {"Network", "Network Summary"}:
        return _metric_row(
            _metric("ifaces", str(len(state.network.interfaces))),
            _metric("routes", str(len(state.network.routes))),
            _metric("dns", str(len(state.network.dns.servers))),
            _metric("fw", _firewall_state_text(state), style="grey70"),
        )
    if selected_section == "Interfaces":
        up_count = sum(1 for interface in state.network.interfaces if interface.is_up)
        return _metric_row(
            _metric("ifaces", str(len(state.network.interfaces))),
            _metric("up", str(up_count)),
            _metric("ports", str(len(state.network.listening_ports))),
            _metric("fw", _firewall_state_text(state), style="grey70"),
        )
    if selected_section == "Routes & DNS":
        return _metric_row(
            _metric("routes", str(len(state.network.routes))),
            _metric("dns", str(len(state.network.dns.servers))),
            _metric("search", str(len(state.network.dns.search))),
            _metric("source", state.network.dns.source or "n/a", style="grey70"),
        )
    if selected_section == "Ports & Connections":
        return _metric_row(
            _metric("listen", str(len(state.network.listening_ports))),
            _metric("active", str(len(state.network.active_connections))),
            _metric("tcp", str(sum(1 for port in state.network.listening_ports if port.protocol.lower() == "tcp"))),
            _metric("udp", str(sum(1 for port in state.network.listening_ports if port.protocol.lower() == "udp"))),
        )
    if selected_section == "Firewall":
        return _metric_row(
            _metric("backend", state.network.firewall.backend or "n/a", style="grey70"),
            _metric("enabled", _bool_text(state.network.firewall.enabled)),
            _metric("available", _bool_text(state.network.firewall.availability.available)),
            _metric("summary", _truncate_text(state.network.firewall.summary or "n/a", max_length=18), style="grey70"),
        )
    if selected_section == "Processes":
        top_process = state.processes.entries[0] if state.processes.entries else None
        return _metric_row(
            _metric("tracked", str(state.processes.total_processes)),
            _metric("top", _truncate_text(top_process.name, max_length=18) if top_process else "n/a", style="grey70"),
            _metric("cpu", f"{top_process.cpu_percent:.1f}%" if top_process else "n/a", style=_threshold_style(top_process.cpu_percent, warning=40.0, critical=75.0) if top_process else "grey62"),
        )
    if selected_section == "Services":
        active_services = sum(1 for service in state.services.services if service.active_state == "active")
        failed_services = sum(1 for service in state.services.services if service.is_failed)
        return _metric_row(
            _metric("manager", state.services.manager or "n/a", style="grey70"),
            _metric("active", str(active_services)),
            _metric("failed", str(failed_services), style="bold red" if failed_services else "white"),
            _metric("shown", str(min(len(state.services.services), 24))),
        )
    if selected_section == "Storage":
        hottest_disk = _hottest_disk(state)
        return _metric_row(
            _metric("mounts", str(len(state.storage.mounts))),
            _metric("disks", str(len(state.storage.disks))),
            _metric(
                "hot",
                _celsius_to_text(hottest_disk.temperature_celsius) if hottest_disk is not None else "n/a",
                style=_temperature_style(hottest_disk.temperature_celsius if hottest_disk is not None else None, warning=50.0, critical=60.0),
            ),
            _metric("io", str(len(state.storage.io_counters))),
        )
    if selected_section == "Logs":
        latest_source = state.logs.entries[-1].unit or state.logs.entries[-1].source if state.logs.entries else "n/a"
        return _metric_row(
            _metric("backend", state.runtime.log_backend or "n/a", style="grey70"),
            _metric("entries", str(len(state.logs.entries))),
            _metric("live", "on" if state.logs.live_enabled else "off"),
            _metric("latest", _truncate_text(latest_source, max_length=18), style="grey70"),
        )
    if selected_section in {"Security", "Security Posture"}:
        critical_findings = sum(1 for finding in state.security.findings if finding.severity == "critical")
        warning_findings = sum(1 for finding in state.security.findings if finding.severity == "warning")
        sudo_label, sudo_style = _security_sudo_status(state)
        access_label, access_style = _security_access_label(state)
        return _metric_row(
            _metric("crit", str(critical_findings), style="bold red" if critical_findings else "white"),
            _metric("warn", str(warning_findings), style="bold white" if warning_findings else "grey62"),
            _metric("sudo", sudo_label, style=sudo_style),
            _metric("access", access_label, style=access_style),
        )
    if selected_section == "Access & Identity":
        return _metric_row(
            _metric("users", str(len(state.security.users))),
            _metric("groups", str(len(state.security.groups))),
            _metric("sudo", _bool_text(state.security.sudo_configured), style="grey70"),
            _metric("policy", "non-interactive" if state.security.sudo_non_interactive else "bounded", style="grey70"),
        )
    if selected_section == "Exposure":
        critical_findings = sum(1 for finding in state.security.findings if finding.severity == "critical")
        warning_findings = sum(1 for finding in state.security.findings if finding.severity == "warning")
        return _metric_row(
            _metric("exposed", str(len(state.security.exposed_services))),
            _metric("crit", str(critical_findings), style="bold red" if critical_findings else "white"),
            _metric("warn", str(warning_findings), style="bold white" if warning_findings else "grey62"),
            _metric("findings", str(len(state.security.findings))),
        )
    if selected_section == "Sessions":
        remote_count = sum(1 for session in state.sessions.current_sessions if session.host)
        return _metric_row(
            _metric("current", str(len(state.sessions.current_sessions))),
            _metric("remote", str(remote_count)),
            _metric("recent", str(len(state.sessions.recent_logins))),
        )
    if selected_section == "Power":
        thermal_max = max((sensor.current_celsius for sensor in state.power.thermal_sensors), default=None)
        return _metric_row(
            _metric("battery", f"{state.power.battery_percent:.1f}%" if state.power.battery_percent is not None else "n/a"),
            _metric("plugged", _bool_text(state.power.power_plugged)),
            _metric("thermals", _celsius_to_text(thermal_max)),
            _metric("gov", str(len(state.power.cpu_governors))),
        )
    if selected_section == "Kernel":
        return _metric_row(
            _metric("release", state.os_state.kernel_release or "n/a", style="grey70"),
            _metric("tunables", str(len(state.os_state.sysctl_values))),
        )
    if selected_section == "Packages":
        first_update = next((package.name for package in state.packages.entries if package.update_version), None)
        return _metric_row(
            _metric("manager", state.packages.manager or "n/a", style="grey70"),
            _metric("installed", str(state.packages.installed_count)),
            _metric("updates", str(state.packages.update_count) if state.packages.update_count is not None else "n/a"),
            _metric("sample", _truncate_text(first_update or "current", max_length=18), style="grey70"),
        )
    if selected_section == "Runtime Backends":
        return _metric_row(
            _metric("distro", _runtime_distro_label(state), style="grey70"),
            _metric("init", state.runtime.init_system or "n/a"),
            _metric("svc", state.runtime.service_manager or "n/a"),
            _metric("log", state.runtime.log_backend or "n/a"),
        )
    if selected_section == "Audit":
        warning_count = sum(1 for finding in state.audit.findings if finding.severity == "warning")
        critical_count = sum(1 for finding in state.audit.findings if finding.severity == "critical")
        enabled_state = state.audit.audit_details.get("enabled", state.audit.audit_status or "n/a")
        return _metric_row(
            _metric("enabled", enabled_state, style="grey70"),
            _metric("warn", str(warning_count), style="bold white" if warning_count else "grey62"),
            _metric("crit", str(critical_count), style="bold red" if critical_count else "white"),
            _metric("auditd", _bool_text(state.audit.auditd_active)),
        )
    if selected_section == "Containers":
        sample_name = state.containers.containers[0].name if state.containers.containers else "n/a"
        return _metric_row(
            _metric("runtime", state.containers.runtime or "n/a", style="grey70"),
            _metric("running", str(state.containers.running_count)),
            _metric("images", str(state.containers.image_count)),
            _metric("sample", _truncate_text(sample_name, max_length=18), style="grey70"),
        )
    if selected_section == "Events":
        latest = state.events[-1] if state.events else None
        return _metric_row(
            _metric("count", str(len(state.events))),
            _metric("latest", latest.severity if latest else "n/a", style="grey70"),
            _metric("source", _truncate_text(latest.source, max_length=18) if latest else "n/a", style="grey70"),
        )
    return None


def _render_hardware(state: SystemState) -> RenderableType:
    load_style = _threshold_style(state.hardware.cpu.load_percent, warning=65.0, critical=85.0)
    memory_style = _threshold_style(state.hardware.memory.percent, warning=75.0, critical=90.0)
    busy_cores = sorted(state.hardware.cpu.per_core, key=lambda core: core.percent, reverse=True)[:6]
    hottest_thermal = _hottest_thermal_sensor(state)
    hottest_disk = _hottest_disk(state)
    thermal_sample = sorted(state.power.thermal_sensors, key=lambda sensor: sensor.current_celsius, reverse=True)[:4]
    lines: list[Text] = [
        *_section_header("Hardware", max(state.hardware.refreshed_at, state.power.refreshed_at, state.storage.refreshed_at)),
        _metric_row(
            _metric(
                "CPU",
                f"{state.hardware.cpu.logical_cores}c / {state.hardware.cpu.physical_cores or 'n/a'}p",
            ),
            _metric("Mem", f"{state.hardware.memory.percent:.1f}%", style=memory_style),
        ),
        _metric_row(
            _metric("GPU", _gpu_summary_text(state), style="grey70" if state.hardware.gpus else "grey62"),
        ),
        _metric_row(
            _metric(
                "Thermals",
                _celsius_to_text(hottest_thermal.current_celsius) if hottest_thermal is not None else "n/a",
                style=_temperature_style(hottest_thermal.current_celsius if hottest_thermal is not None else None, warning=70.0, critical=85.0),
            ),
            _metric(
                "Disk temp",
                _celsius_to_text(hottest_disk.temperature_celsius) if hottest_disk is not None else "n/a",
                style=_temperature_style(hottest_disk.temperature_celsius if hottest_disk is not None else None, warning=50.0, critical=60.0),
            ),
        ),
        Text(),
        _subheading("CPU"),
        _metric_row(
            _metric("Model", _truncate_text(state.hardware.cpu.model_name or "n/a", max_length=28), style="white"),
            _metric("Arch", state.hardware.cpu.architecture or "n/a"),
        ),
        _metric_row(
            _metric("Sample", f"{state.hardware.cpu.load_percent:.1f}%", style=load_style),
            _metric("Freq", _mhz_to_text(state.hardware.cpu.frequency_current_mhz)),
            _metric("Max", _mhz_to_text(state.hardware.cpu.frequency_max_mhz)),
        ),
    ]
    if busy_cores:
        lines.extend([Text(), _subheading("Busiest cores")])
        busy_cores_metrics = [_metric(f"cpu{core.index}", f"{core.percent:.1f}%") for core in busy_cores]
        lines.append(_metric_row(*busy_cores_metrics))

    lines.extend([
        Text(),
        _subheading("Memory"),
        _metric_row(
            _metric("Used", _bytes_to_text(state.hardware.memory.used_bytes)),
            _metric("Avail", _bytes_to_text(state.hardware.memory.available_bytes)),
            _metric("Total", _bytes_to_text(state.hardware.memory.total_bytes)),
            _metric("Pct", f"{state.hardware.memory.percent:.1f}%", style=memory_style),
        ),
        _metric_row(
            _metric("Swap used", _bytes_to_text(state.hardware.memory.swap_used_bytes)),
            _metric("Swap total", _bytes_to_text(state.hardware.memory.swap_total_bytes)),
            _metric("Swap pct", f"{state.hardware.memory.swap_percent:.1f}%"),
        ),
    ])
    if state.hardware.gpus:
        for index, gpu in enumerate(state.hardware.gpus[:4], start=1):
            lines.append(
                _metric_row(
                    _metric(f"GPU {index}", _gpu_identity_text(gpu, max_length=30), style="white"),
                    _metric("driver", gpu.driver or "n/a", style="grey70"),
                    _metric("bus", gpu.bus_id or "n/a", style="grey70"),
                    _metric("active", _gpu_workload_count_text(gpu), style="white" if gpu.workloads else "grey62"),
                )
            )
            lines.append(
                _metric_row(
                    _metric("mem", _gpu_memory_text(gpu), style="grey70"),
                    _metric(
                        "util",
                        _percent_text(gpu.utilization_percent),
                        style=_threshold_style(gpu.utilization_percent, warning=70.0, critical=90.0) if gpu.utilization_percent is not None else "grey62",
                    ),
                    _metric(
                        "temp",
                        _celsius_to_text(gpu.temperature_celsius),
                        style=_temperature_style(gpu.temperature_celsius, warning=75.0, critical=88.0),
                    ),
                    _metric("source", gpu.workload_source or gpu.backend or "inventory", style="grey62"),
                )
            )
            workload_summary = _gpu_workload_summary_text(gpu)
            if workload_summary is not None:
                lines.append(Text(f"  running {workload_summary}", style="grey70"))
                for workload in gpu.workloads[:2]:
                    if workload.command:
                        lines.append(Text(f"  cmd {_truncate_text(_collapse_whitespace(workload.command), max_length=92)}", style="grey50"))
            elif gpu.workload_source:
                lines.append(Text("  running no active compute workloads were sampled", style="grey50"))
            else:
                lines.append(Text("  running workload sampling unavailable for this backend", style="grey50"))
    else:
        lines.append(Text("No dedicated GPU inventory or driver telemetry is currently available on this host.", style="grey62"))

    lines.extend([
        Text(),
        _subheading("Thermals"),
    ])
    if thermal_sample:
        for sensor in thermal_sample:
            lines.append(
                _metric_row(
                    _metric(sensor.label, _celsius_to_text(sensor.current_celsius), style="white"),
                    _metric("source", sensor.source, style="grey70"),
                    _metric("high", _celsius_to_text(sensor.high_celsius), style="grey62"),
                )
            )
    else:
        lines.append(Text("No thermal sensors are currently exposed by the kernel on this host.", style="grey62"))

    lines.extend([
        Text(),
        _subheading("Storage devices"),
    ])
    if state.storage.disks:
        for disk in state.storage.disks[:4]:
            smart_value = disk.smart_health or ("available" if disk.smart_available else "n/a")
            smart_style = "bold red" if (disk.smart_health or "").lower() not in {"", "passed", "ok"} else "white"
            lines.append(
                _metric_row(
                    _metric(disk.name, _truncate_text(disk.model or "n/a", max_length=30), style="white"),
                    _metric("size", _bytes_to_text(disk.size_bytes), style="grey70"),
                    _metric("transport", disk.transport or "-", style="grey70"),
                )
            )
            lines.append(
                _metric_row(
                    _metric("smart", smart_value, style=smart_style),
                    _metric(
                        "temp",
                        _celsius_to_text(disk.temperature_celsius),
                        style=_temperature_style(disk.temperature_celsius, warning=50.0, critical=60.0),
                    ),
                )
            )
    else:
        lines.append(Text("No block-device inventory is currently available in the storage snapshot.", style="grey62"))

    lines.extend([
        Text(),
        _subheading("Bus inventory"),
        _metric_row(
            _metric("PCI", str(len(state.hardware.pci_devices))),
            _metric("USB", str(len(state.hardware.usb_devices))),
        ),
    ])
    if state.hardware.pci_devices or state.hardware.usb_devices:
        lines.extend([Text(), _subheading("Inventory sample")])
        for device in [*state.hardware.pci_devices[:3], *state.hardware.usb_devices[:3]]:
            lines.append(
                _metric_row(
                    _metric(device.category, device.identifier, style="white"),
                    _metric("desc", device.description or "n/a", style="grey70"),
                )
            )
    return _centered(Group(*lines))


def _render_overview(state: SystemState) -> RenderableType:
    critical_findings = sum(1 for finding in state.security.findings if finding.severity == "critical")
    failed_services = sum(1 for service in state.services.services if service.is_failed)
    lines: list[Text] = [
        *_section_header("Overview", state.timestamp),
        _metric_row(
            _metric("Host", state.os_state.hostname or "n/a"),
            _metric("Distro", _runtime_distro_label(state), style="grey70"),
            _metric("Load", f"{state.hardware.cpu.load_percent:.1f}%", style=_threshold_style(state.hardware.cpu.load_percent, warning=65.0, critical=85.0)),
            _metric("Mem", f"{state.hardware.memory.percent:.1f}%", style=_threshold_style(state.hardware.memory.percent, warning=75.0, critical=90.0)),
        ),
        _metric_row(
            _metric("Proc", str(state.processes.total_processes)),
            _metric("Svc fail", str(failed_services), style="bold red" if failed_services else "white"),
            _metric("Findings", str(len(state.security.findings))),
            _metric("Critical", str(critical_findings), style="bold red" if critical_findings else "white"),
        ),
        _metric_row(
            _metric("Pkg upd", str(state.packages.update_count) if state.packages.update_count is not None else "n/a"),
            _metric("Ctr run", f"{state.containers.running_count}/{state.containers.total_count}"),
            _metric("Sessions", str(len(state.sessions.current_sessions))),
            _metric("Audit", str(len(state.audit.findings))),
        ),
        Text(),
        _subheading("Surface"),
        _metric_row(
            _metric("Interfaces", str(len(state.network.interfaces))),
            _metric("Routes", str(len(state.network.routes))),
            _metric("Ports", str(len(state.network.listening_ports))),
            _metric("Mounts", str(len(state.storage.mounts))),
        ),
    ]
    return _centered(Group(*lines))


def _render_system(state: SystemState) -> RenderableType:
    lines: list[Text] = [
        *_section_header("System", state.os_state.refreshed_at),
        _metric_row(
            _metric("Host", state.os_state.hostname or "n/a"),
            _metric("FQDN", state.os_state.fqdn or "n/a"),
            _metric("Distro", _runtime_distro_label(state), style="grey70"),
        ),
        _metric_row(
            _metric("Uptime", _seconds_to_text(state.os_state.uptime_seconds)),
            _metric("Loadavg", ", ".join(f"{value:.2f}" for value in state.os_state.load_average)),
            _metric("Init", state.runtime.init_system or "n/a"),
        ),
        Text(),
        _subheading("Runtime"),
        _metric_row(
            _metric("Rel", state.runtime.distro_version or "n/a"),
            _metric("Logs", state.runtime.log_backend or "n/a"),
            _metric("Pkg", state.runtime.package_manager or "n/a"),
        ),
        _metric_row(
            _metric("Services", state.runtime.service_manager or "n/a"),
            _metric("Security", state.runtime.security_backend or "n/a"),
            _metric("Firewall", state.runtime.firewall_backend or "n/a"),
        ),
        _metric_row(
            _metric("Containers", state.runtime.container_runtime or "n/a"),
        ),
    ]
    return _centered(Group(*lines))


def _render_system_health(state: SystemState) -> RenderableType:
    failed_services = sum(1 for service in state.services.services if service.is_failed)
    lines: list[Text] = [
        *_section_header("System Health", max(state.hardware.refreshed_at, state.os_state.refreshed_at, state.runtime.refreshed_at)),
        _metric_row(
            _metric("Host", state.os_state.hostname or "n/a"),
            _metric("FQDN", state.os_state.fqdn or "n/a", style="grey70"),
            _metric("Distro", _runtime_distro_label(state), style="grey70"),
        ),
        _metric_row(
            _metric("Uptime", _seconds_to_text(state.os_state.uptime_seconds)),
            _metric("Loadavg", ", ".join(f"{value:.2f}" for value in state.os_state.load_average), style="grey70"),
            _metric("CPU", f"{state.hardware.cpu.load_percent:.1f}%", style=_threshold_style(state.hardware.cpu.load_percent, warning=65.0, critical=85.0)),
            _metric("Mem", f"{state.hardware.memory.percent:.1f}%", style=_threshold_style(state.hardware.memory.percent, warning=75.0, critical=90.0)),
        ),
        _metric_row(
            _metric("Tracked proc", str(state.processes.total_processes)),
            _metric("Failed svc", str(failed_services), style="bold red" if failed_services else "white"),
            _metric("Init", state.runtime.init_system or "n/a", style="grey70"),
            _metric("Svc mgr", state.runtime.service_manager or "n/a", style="grey70"),
        ),
    ]
    return _centered(Group(*lines))


def _render_performance(state: SystemState) -> RenderableType:
    lines: list[Text] = [
        *_section_header("Performance", max(state.hardware.refreshed_at, state.processes.refreshed_at, state.os_state.refreshed_at)),
        _metric_row(
            _metric("CPU sample", f"{state.hardware.cpu.load_percent:.1f}%", style=_threshold_style(state.hardware.cpu.load_percent, warning=65.0, critical=85.0)),
            _metric("Loadavg", ", ".join(f"{value:.2f}" for value in state.os_state.load_average), style="grey70"),
            _metric("Mem", f"{state.hardware.memory.percent:.1f}%", style=_threshold_style(state.hardware.memory.percent, warning=75.0, critical=90.0)),
            _metric("Swap", f"{state.hardware.memory.swap_percent:.1f}%"),
            _metric("Tracked", str(state.processes.total_processes)),
        ),
        Text(),
        _subheading("Hot processes"),
    ]
    for process in state.processes.entries[:8]:
        lines.append(
            _metric_row(
                _metric(process.name, f"pid {process.pid}"),
                _metric("cpu", f"{process.cpu_percent:.1f}%", style=_threshold_style(process.cpu_percent, warning=40.0, critical=75.0)),
                _metric("mem", f"{process.memory_percent:.1f}%", style=_threshold_style(process.memory_percent, warning=20.0, critical=40.0)),
            )
        )
    return _centered(Group(*lines))


def _render_network(state: SystemState) -> RenderableType:
    lines: list[Text] = [
        *_section_header("Interfaces", state.network.refreshed_at),
        _metric_row(
            _metric("Interfaces", str(len(state.network.interfaces))),
            _metric("Up", str(sum(1 for interface in state.network.interfaces if interface.is_up))),
            _metric("Listening", str(len(state.network.listening_ports))),
            _metric("Firewall", _firewall_state_text(state), style=_availability_style(state.network.firewall.availability.available)),
        ),
        Text(),
        _subheading("Interfaces"),
    ]
    for interface in state.network.interfaces[:8]:
        address = interface.addresses[0].address if interface.addresses else "no-address"
        lines.append(
            _metric_row(
                _metric(interface.name, "up" if interface.is_up else "down", style="white" if interface.is_up else "grey62"),
                _metric("addr", address),
                _metric("rx", _bytes_to_text(interface.rx_bytes)),
                _metric("tx", _bytes_to_text(interface.tx_bytes)),
            )
        )
    return _centered(Group(*lines))


def _render_network_summary(state: SystemState) -> RenderableType:
    default_route = next((route for route in state.network.routes if route.destination == "default"), None)
    up_count = sum(1 for interface in state.network.interfaces if interface.is_up)
    lines: list[Text] = [
        *_section_header("Network Summary", state.network.refreshed_at),
        _metric_row(
            _metric("Interfaces", f"{up_count}/{len(state.network.interfaces)} up"),
            _metric("Routes", str(len(state.network.routes))),
            _metric("DNS", str(len(state.network.dns.servers))),
            _metric("Firewall", _firewall_state_text(state), style=_availability_style(state.network.firewall.availability.available)),
        ),
        _metric_row(
            _metric("Listening", str(len(state.network.listening_ports))),
            _metric("Active", str(len(state.network.active_connections))),
            _metric("Resolver", state.network.dns.source or "n/a", style="grey70"),
        ),
        Text(),
        _subheading("Primary path"),
        Text(
            (
                f"Default route via {default_route.gateway or '-'} on {default_route.device or '-'}"
                if default_route is not None
                else "No default route is currently present in the sampled routing table."
            ),
            style="grey70",
        ),
        Text(),
        _subheading("Resolver sample"),
        Text(", ".join(state.network.dns.servers[:4]) or "No DNS servers are currently configured.", style="grey70"),
    ]
    return _centered(Group(*lines))


def _render_routes_dns(state: SystemState) -> RenderableType:
    lines: list[Text] = [
        *_section_header("Routes & DNS", state.network.refreshed_at),
        _metric_row(
            _metric("Routes", str(len(state.network.routes))),
            _metric("DNS", str(len(state.network.dns.servers))),
            _metric("Search", str(len(state.network.dns.search))),
            _metric("Source", state.network.dns.source or "n/a", style="grey70"),
        ),
        Text(),
        _subheading("Routes"),
    ]
    if state.network.routes:
        for route in state.network.routes[:8]:
            lines.append(
                _metric_row(
                    _metric("dst", route.destination),
                    _metric("via", route.gateway or "-"),
                    _metric("dev", route.device or "-"),
                    _metric("metric", str(route.metric or "-"), style="grey70"),
                )
            )
    else:
        lines.append(Text("No routes are currently present in the sampled table.", style="grey62"))
    lines.extend([Text(), _subheading("Resolver")])
    if state.network.dns.servers:
        lines.append(Text(", ".join(state.network.dns.servers), style="white"))
        if state.network.dns.search:
            lines.append(Text(f"search: {', '.join(state.network.dns.search)}", style="grey70"))
    else:
        lines.append(Text("No DNS servers are currently configured.", style="grey62"))
    return _centered(Group(*lines))


def _render_ports_connections(state: SystemState) -> RenderableType:
    lines: list[Text] = [
        *_section_header("Ports & Connections", state.network.refreshed_at),
        _metric_row(
            _metric("Listening", str(len(state.network.listening_ports))),
            _metric("Active", str(len(state.network.active_connections))),
            _metric("TCP", str(sum(1 for port in state.network.listening_ports if port.protocol.lower() == "tcp"))),
            _metric("UDP", str(sum(1 for port in state.network.listening_ports if port.protocol.lower() == "udp"))),
        ),
        Text(),
        _subheading("Listening sockets"),
    ]
    if state.network.listening_ports:
        for port in state.network.listening_ports[:8]:
            lines.append(
                _metric_row(
                    _metric("sock", f"{port.protocol.upper()} {port.local_address}:{port.local_port}"),
                    _metric("proc", port.process_name or (str(port.pid) if port.pid is not None else "unknown"), style="grey70"),
                )
            )
    else:
        lines.append(Text("No listening sockets are currently present in the sampled snapshot.", style="grey62"))
    lines.extend([Text(), _subheading("Active connections")])
    if state.network.active_connections:
        for connection in state.network.active_connections[:8]:
            lines.append(
                _metric_row(
                    _metric(connection.protocol.upper(), connection.status, style="white"),
                    _metric("flow", _connection_summary_text(connection), style="grey70"),
                )
            )
    else:
        lines.append(Text("No active connections were captured in the current snapshot.", style="grey62"))
    return _centered(Group(*lines))


def _render_firewall(state: SystemState) -> RenderableType:
    availability = state.network.firewall.availability
    lines: list[Text] = [
        *_section_header("Firewall", state.network.refreshed_at),
        _metric_row(
            _metric("Backend", state.network.firewall.backend or state.runtime.firewall_backend or "n/a", style="bold white"),
            _metric("Enabled", _bool_text(state.network.firewall.enabled)),
            _metric("Available", _bool_text(availability.available), style=_availability_style(availability.available)),
        ),
        Text(),
        _subheading("Summary"),
        Text(state.network.firewall.summary or "No firewall summary text was reported by the detected backend.", style="grey70"),
    ]
    if availability.reason:
        lines.extend([Text(), Text(availability.reason, style="grey62")])
    return _centered(Group(*lines))


def _render_processes(state: SystemState) -> RenderableType:
    lines: list[Text] = [
        *_section_header("Processes", state.processes.refreshed_at),
        _metric_row(
            _metric("Tracked", str(state.processes.total_processes)),
            _metric("Shown", str(min(len(state.processes.entries), 20))),
        ),
        Text(),
        _subheading("Top Processes"),
    ]
    for process in state.processes.entries[:12]:
        cpu_style = _threshold_style(process.cpu_percent, warning=40.0, critical=75.0)
        memory_style = _threshold_style(process.memory_percent, warning=20.0, critical=40.0)
        lines.append(
            _metric_row(
                _metric("pid", str(process.pid)),
                _metric("cpu", f"{process.cpu_percent:>5.1f}%", style=cpu_style),
                _metric("mem", f"{process.memory_percent:>5.1f}%", style=memory_style),
                _metric("proc", process.name),
            )
        )
    return _centered(Group(*lines))


def _render_services(state: SystemState) -> RenderableType:
    active_services = sum(1 for service in state.services.services if service.active_state == "active")
    failed_services = sum(1 for service in state.services.services if service.is_failed)
    enabled_services = sum(1 for service in state.services.services if service.is_enabled)
    lines: list[Text] = [
        *_section_header("Services", state.services.refreshed_at),
        _metric_row(
            _metric("Manager", state.services.manager or "n/a", style="bold white" if state.services.manager else "grey62"),
            _metric("Units", str(len(state.services.services))),
            _metric("Active", str(active_services)),
            _metric("Enabled", str(enabled_services)),
            _metric("Failed", str(failed_services), style="bold red" if failed_services else "white"),
        ),
        Text(),
        _subheading("Units"),
    ]
    for service in state.services.services[:12]:
        style = _service_style(service.is_failed, service.active_state)
        lines.append(
            _metric_row(
                _metric("unit", service.name, style=style),
                _metric("state", service.active_state.upper(), style=style),
                _metric("sub", service.sub_state, style=style),
                _metric("load", service.load_state, style="grey70"),
                _metric("file", service.unit_file_state, style="white" if service.is_enabled else "grey62"),
            )
        )
        if service.description:
            lines.append(Text(f"  {service.description}", style="grey70"))
    return _centered(Group(*lines))


def _render_logs(state: SystemState) -> RenderableType:
    access_label, access_style = _collection_access_label(
        elevated=state.logs.collection_access.elevated,
        partial=state.logs.collection_access.partial,
    )
    lines: list[Text] = [
        *_section_header("Logs", state.logs.refreshed_at),
        _metric_row(
            _metric("Entries", str(len(state.logs.entries))),
            _metric("Live", "on" if state.logs.live_enabled else "off"),
            _metric("Access", access_label, style=access_style),
            _metric("Backend", state.runtime.log_backend or "n/a", style="grey70"),
        ),
        Text(),
        _subheading("Journal"),
    ]
    if state.logs.collection_access.detail:
        lines.extend([Text(state.logs.collection_access.detail, style="grey62"), Text()])
    for entry in state.logs.entries[-15:]:
        priority = (entry.priority or "-").lower()
        priority_style = "bold red" if priority in {"0", "1", "2", "3", "err", "error", "crit", "critical"} else "grey62"
        lines.append(
            Text.assemble(
                (_timestamp_text(entry.timestamp), "grey50"),
                ("  ", ""),
                ((entry.priority or "-").upper(), priority_style),
                ("  ", ""),
                (entry.unit or entry.source, "white"),
                ("  ", ""),
                (entry.message, "grey70"),
            )
        )
    return _centered(Group(*lines))


def _render_security(state: SystemState) -> RenderableType:
    critical_findings = sum(1 for finding in state.security.findings if finding.severity == "critical")
    sudo_label, sudo_style = _security_sudo_status(state)
    access_label, access_style = _security_access_label(state)
    sudo_detail = _bounded_detail_text(state.security.sudo_summary)
    lines: list[Text] = [
        *_section_header("Security", state.security.refreshed_at),
        _metric_row(
            _metric("sudo", sudo_label, style=sudo_style),
            _metric("policy", "non-interactive" if state.security.sudo_non_interactive else "bounded", style="white" if state.security.sudo_non_interactive else "grey62"),
            _metric("users", str(len(state.security.users))),
            _metric("groups", str(len(state.security.groups))),
            _metric("crit", str(critical_findings), style="bold red" if critical_findings else "white"),
        ),
        _metric_row(
            _metric("exposed", str(len(state.security.exposed_services))),
            _metric("access", access_label, style=access_style),
        ),
        Text(),
    ]
    if state.security.collection_access.detail:
        lines.extend([Text(state.security.collection_access.detail, style="grey62"), Text()])
    if sudo_detail:
        lines.extend([_subheading("Sudo policy"), Text(sudo_detail, style="grey62"), Text()])
    lines.append(_subheading("Findings"))
    for finding in state.security.findings[:8]:
        style = _severity_style(finding.severity)
        lines.append(
            Text.assemble(
                (finding.severity.upper(), style),
                ("  ", ""),
                (finding.title, style),
                ("  ", ""),
                ((finding.path or ""), "grey50"),
                ("  ", ""),
                (finding.detail, "grey70"),
            )
        )
    return _centered(Group(*lines))


def _render_security_posture(state: SystemState) -> RenderableType:
    critical_findings = sum(1 for finding in state.security.findings if finding.severity == "critical")
    warning_findings = sum(1 for finding in state.security.findings if finding.severity == "warning")
    access_label, access_style = _security_access_label(state)
    sudo_label, sudo_style = _security_sudo_status(state)
    sudo_detail = _bounded_detail_text(state.security.sudo_summary)
    lines: list[Text] = [
        *_section_header("Security Posture", state.security.refreshed_at),
        _metric_row(
            _metric("Critical", str(critical_findings), style="bold red" if critical_findings else "white"),
            _metric("Warnings", str(warning_findings), style="bold white" if warning_findings else "grey62"),
            _metric("Findings", str(len(state.security.findings))),
            _metric("Access", access_label, style=access_style),
        ),
        _metric_row(
            _metric("sudo", sudo_label, style=sudo_style),
            _metric("configured", _bool_text(state.security.sudo_configured)),
            _metric("policy", "non-interactive" if state.security.sudo_non_interactive else "bounded", style="grey70"),
        ),
        Text(),
    ]
    if state.security.collection_access.detail:
        lines.extend([Text(state.security.collection_access.detail, style="grey62"), Text()])
    if sudo_detail:
        lines.extend([_subheading("Sudo policy"), Text(sudo_detail, style="grey62"), Text()])
    lines.append(_subheading("Top findings"))
    if state.security.findings:
        for finding in state.security.findings[:6]:
            style = _severity_style(finding.severity)
            lines.append(Text.assemble((finding.severity.upper(), style), ("  ", ""), (finding.title, style), ("  ", ""), (finding.detail, "grey70")))
    else:
        lines.append(Text("No security findings are currently present in the bounded snapshot.", style="grey62"))
    return _centered(Group(*lines))


def _render_access_identity(state: SystemState) -> RenderableType:
    lines: list[Text] = [
        *_section_header("Access & Identity", state.security.refreshed_at),
        _metric_row(
            _metric("Users", str(len(state.security.users))),
            _metric("Groups", str(len(state.security.groups))),
            _metric("sudo", _bool_text(state.security.sudo_configured)),
            _metric("auth", _bool_text(state.security.sudo_authenticated), style="grey70"),
        ),
        _metric_row(
            _metric("available", _bool_text(state.security.sudo_available)),
            _metric("policy", "non-interactive" if state.security.sudo_non_interactive else "bounded", style="grey70"),
        ),
        Text(),
        _subheading("Users"),
    ]
    if state.security.users:
        lines.append(Text(", ".join(state.security.users[:16]), style="white"))
    else:
        lines.append(Text("No bounded user inventory is currently available.", style="grey62"))
    lines.extend([Text(), _subheading("Groups")])
    if state.security.groups:
        for group_name, members in list(sorted(state.security.groups.items()))[:6]:
            lines.append(_metric_row(_metric(group_name, ", ".join(members[:6]) or "no sampled members", style="grey70")))
    else:
        lines.append(Text("No bounded group inventory is currently available.", style="grey62"))
    return _centered(Group(*lines))


def _render_exposure(state: SystemState) -> RenderableType:
    risky_findings = [finding for finding in state.security.findings if finding.severity in {"warning", "critical"}]
    lines: list[Text] = [
        *_section_header("Exposure", state.security.refreshed_at),
        _metric_row(
            _metric("Exposed", str(len(state.security.exposed_services))),
            _metric("Risk findings", str(len(risky_findings))),
            _metric("Critical", str(sum(1 for finding in risky_findings if finding.severity == "critical")), style="bold red" if any(finding.severity == "critical" for finding in risky_findings) else "white"),
        ),
        Text(),
        _subheading("Exposed services"),
    ]
    if state.security.exposed_services:
        for port in state.security.exposed_services[:8]:
            lines.append(
                _metric_row(
                    _metric("svc", f"{port.protocol.upper()} {port.local_address}:{port.local_port}"),
                    _metric("proc", port.process_name or (str(port.pid) if port.pid is not None else "unknown"), style="grey70"),
                )
            )
    else:
        lines.append(Text("No exposed services were identified in the bounded snapshot.", style="grey62"))
    lines.extend([Text(), _subheading("Risk findings")])
    if risky_findings:
        for finding in risky_findings[:6]:
            style = _severity_style(finding.severity)
            lines.append(Text.assemble((finding.severity.upper(), style), ("  ", ""), (finding.title, style), ("  ", ""), (finding.detail, "grey70")))
    else:
        lines.append(Text("No warning or critical exposure findings are currently present.", style="grey62"))
    return _centered(Group(*lines))


def _render_storage(state: SystemState) -> RenderableType:
    hottest_disk = _hottest_disk(state)
    lines: list[Text] = [
        *_section_header("Storage", state.storage.refreshed_at),
        _metric_row(
            _metric("Mounts", str(len(state.storage.mounts))),
            _metric("Disks", str(len(state.storage.disks))),
            _metric(
                "Hot disk",
                _celsius_to_text(hottest_disk.temperature_celsius) if hottest_disk is not None else "n/a",
                style=_temperature_style(hottest_disk.temperature_celsius if hottest_disk is not None else None, warning=50.0, critical=60.0),
            ),
            _metric("I/O", str(len(state.storage.io_counters))),
        ),
        Text(),
        _subheading("Mounts"),
    ]
    for mount in state.storage.mounts[:8]:
        inode_style = _threshold_style(mount.inode_used_percent or 0.0, warning=75.0, critical=90.0)
        lines.append(
            _metric_row(
                _metric(mount.mount_point, f"{_bytes_to_text(mount.used_bytes)} / {_bytes_to_text(mount.total_bytes)}"),
                _metric("fs", mount.filesystem),
                _metric("inode", f"{(mount.inode_used_percent or 0.0):.1f}%", style=inode_style),
            )
        )
    lines.extend([Text(), _subheading("Disks")])
    for disk in state.storage.disks[:8]:
        smart_style = "bold red" if (disk.smart_health or "").lower() not in {"", "passed", "ok"} else "white"
        lines.append(
            _metric_row(
                _metric(disk.name, disk.model or "n/a"),
                _metric("temp", _celsius_to_text(disk.temperature_celsius), style=_temperature_style(disk.temperature_celsius, warning=50.0, critical=60.0)),
                _metric("transport", disk.transport or "-"),
                _metric("smart", disk.smart_health or "n/a", style=smart_style),
            )
        )
    return _centered(Group(*lines))


def _render_events(state: SystemState) -> RenderableType:
    warning_count = sum(1 for event in state.events if event.severity == "warning")
    error_count = sum(1 for event in state.events if event.severity == "error")
    lines: list[Text] = [
        *_section_header("Events", state.timestamp),
        _metric_row(
            _metric("Count", str(len(state.events))),
            _metric("Warnings", str(warning_count), style="bold white" if warning_count else "grey62"),
            _metric("Errors", str(error_count), style="bold red" if error_count else "white"),
        ),
        Text(),
        _subheading("Recent"),
    ]
    for event in state.events[-12:]:
        style = _event_style(event.severity)
        lines.append(
            Text.assemble(
                (_timestamp_text(event.timestamp), "grey50"),
                ("  ", ""),
                (event.severity.upper(), style),
                ("  ", ""),
                (event.source, "white"),
                ("  ", ""),
                (event.title, style),
                ("  ", ""),
                (str(event.details), "grey62"),
            )
        )
    return _centered(Group(*lines))


def _render_sessions(state: SystemState) -> RenderableType:
    remote_count = sum(1 for session in state.sessions.current_sessions if session.host)
    lines: list[Text] = [
        *_section_header("Sessions", state.sessions.refreshed_at),
        _metric_row(
            _metric("Current", str(len(state.sessions.current_sessions))),
            _metric("Remote", str(remote_count)),
            _metric("Recent", str(len(state.sessions.recent_logins))),
        ),
        Text(),
        _subheading("Current sessions"),
    ]
    if state.sessions.current_sessions:
        for session in state.sessions.current_sessions[:6]:
            started = _timestamp_text(session.started_at) if session.started_at else "unknown"
            host = session.host or "local"
            terminal = session.terminal or "n/a"
            lines.append(
                _metric_row(
                    _metric(session.username, f"{terminal} @ {host}", style="white"),
                    _metric("since", started, style="grey70"),
                )
            )
    else:
        lines.append(Text("No active user sessions are currently reported by psutil on this host.", style="grey62"))
    lines.extend([Text(), _subheading("Recent logins")])
    if state.sessions.recent_logins:
        for entry in state.sessions.recent_logins[:4]:
            lines.append(Text(entry.summary, style="grey70"))
    else:
        lines.append(Text("No recent login history was returned by the local `last` command.", style="grey62"))
    return _centered(Group(*lines))


def _render_power(state: SystemState) -> RenderableType:
    thermal_max = max((sensor.current_celsius for sensor in state.power.thermal_sensors), default=None)
    governor_summary = ", ".join(
        f"{name}:{count}" for name, count in sorted(state.power.cpu_governors.items())
    ) or "n/a"
    lines: list[Text] = [
        *_section_header("Power", state.power.refreshed_at),
        _metric_row(
            _metric("Battery", f"{state.power.battery_percent:.1f}%" if state.power.battery_percent is not None else "n/a"),
            _metric("Plugged", _bool_text(state.power.power_plugged)),
            _metric("Thermals", _celsius_to_text(thermal_max)),
            _metric("Fans", str(len(state.power.fan_sensors))),
        ),
        Text(),
        _subheading("Governors"),
        Text(governor_summary, style="white" if state.power.cpu_governors else "grey62"),
    ]
    if not state.power.availability.available and state.power.availability.reason:
        lines.extend([Text(), Text(state.power.availability.reason, style="grey62")])
    elif not state.power.battery_present:
        lines.extend(
            [
                Text(),
                Text(
                    "Battery telemetry is not present on this host; thermal and governor data remain available when exposed by the kernel.",
                    style="grey62",
                ),
            ]
        )
    if state.power.thermal_sensors:
        lines.extend([Text(), _subheading("Thermal sensors")])
        for sensor in state.power.thermal_sensors[:4]:
            lines.append(
                _metric_row(
                    _metric(sensor.label, _celsius_to_text(sensor.current_celsius), style="white"),
                    _metric("source", sensor.source, style="grey70"),
                )
            )
    return _centered(Group(*lines))


def _render_kernel(state: SystemState) -> RenderableType:
    lines: list[Text] = [
        *_section_header("Kernel", state.os_state.refreshed_at),
        _metric_row(
            _metric("Release", state.os_state.kernel_release or "n/a"),
            _metric("Version", state.os_state.kernel_version or "n/a"),
        ),
        Text(),
        _subheading("Tunables"),
    ]
    if state.os_state.sysctl_values:
        for key, value in sorted(state.os_state.sysctl_values.items()):
            lines.append(_metric_row(_metric(key, value)))
    else:
        lines.append(Text("No sampled sysctl values are available yet.", style="grey62"))
    return _centered(Group(*lines))


def _render_packages(state: SystemState) -> RenderableType:
    sample_entries = sorted(
        state.packages.entries,
        key=lambda package: (package.update_version is None, package.name.casefold()),
    )[:6]
    lines: list[Text] = [
        *_section_header("Packages", state.packages.refreshed_at),
        _metric_row(
            _metric("Manager", state.packages.manager or "n/a", style="bold white" if state.packages.manager else "grey62"),
            _metric("Installed", str(state.packages.installed_count)),
            _metric("Updates", str(state.packages.update_count) if state.packages.update_count is not None else "n/a"),
        ),
        Text(),
        _subheading("Inventory sample"),
    ]
    if not state.packages.availability.available and state.packages.availability.reason:
        lines.append(Text(state.packages.availability.reason, style="grey62"))
    elif sample_entries:
        for package in sample_entries:
            version_label = package.version if package.version != "unknown" else "version n/a"
            metrics = [
                _metric(package.name, version_label, style="white"),
                _metric(
                    "status",
                    f"update -> {package.update_version}" if package.update_version else "current",
                    style="bold white" if package.update_version else "grey62",
                ),
            ]
            if package.architecture:
                metrics.append(_metric("arch", package.architecture, style="grey70"))
            lines.append(_metric_row(*metrics))
            if package.summary:
                lines.append(Text(f"  {_truncate_text(package.summary, max_length=92)}", style="grey62"))
    else:
        lines.append(Text("The detected package manager did not return a bounded inventory sample.", style="grey62"))
    return _centered(Group(*lines))


def _render_runtime_backends(state: SystemState) -> RenderableType:
    lines: list[Text] = [
        *_section_header("Runtime Backends", state.runtime.refreshed_at),
        _metric_row(
            _metric("Distro", _runtime_distro_label(state), style="grey70"),
            _metric("Release", state.runtime.distro_version or "n/a"),
            _metric("Init", state.runtime.init_system or "n/a"),
        ),
        _metric_row(
            _metric("Services", state.runtime.service_manager or "n/a"),
            _metric("Logs", state.runtime.log_backend or "n/a"),
            _metric("Packages", state.runtime.package_manager or "n/a"),
        ),
        _metric_row(
            _metric("Firewall", state.runtime.firewall_backend or "n/a"),
            _metric("Security", state.runtime.security_backend or "n/a"),
            _metric("Containers", state.runtime.container_runtime or "n/a"),
        ),
        Text(),
        _subheading("Backend availability"),
    ]
    if state.backend_status:
        for backend_name, availability in sorted(state.backend_status.items()):
            style = _availability_style(availability.available)
            lines.append(
                _metric_row(
                    _metric(backend_name, "available" if availability.available else "unavailable", style=style),
                    _metric("detail", availability.reason or "no additional details", style="grey70"),
                )
            )
    else:
        lines.append(Text("No backend availability details have been recorded yet.", style="grey62"))
    return _centered(Group(*lines))


def _render_audit(state: SystemState) -> RenderableType:
    warning_count = sum(1 for finding in state.audit.findings if finding.severity == "warning")
    critical_count = sum(1 for finding in state.audit.findings if finding.severity == "critical")
    access_label, access_style = _collection_access_label(
        elevated=state.audit.collection_access.elevated,
        partial=state.audit.collection_access.partial,
    )
    lines: list[Text] = [
        *_section_header("Audit", state.audit.refreshed_at),
        _metric_row(
            _metric("Critical", str(critical_count), style="bold red" if critical_count else "white"),
            _metric("Warnings", str(warning_count), style="bold white" if warning_count else "grey62"),
            _metric("Findings", str(len(state.audit.findings))),
            _metric("Access", access_label, style=access_style),
        ),
        _metric_row(
            _metric("SELinux", state.audit.selinux_mode or _bool_text(state.audit.selinux_enabled), style="white"),
            _metric(
                "AppArmor",
                (
                    f"{_bool_text(state.audit.apparmor_enabled)} ({state.audit.apparmor_profiles_loaded})"
                    if state.audit.apparmor_profiles_loaded is not None
                    else _bool_text(state.audit.apparmor_enabled)
                ),
                style="white",
            ),
            _metric("auditd", _bool_text(state.audit.auditd_active), style="white"),
        ),
        Text(),
        _subheading("Backend findings"),
    ]
    if state.audit.collection_access.detail:
        lines.extend([Text(state.audit.collection_access.detail, style="grey62"), Text()])
    if not state.audit.availability.available and state.audit.availability.reason:
        lines.append(Text(state.audit.availability.reason, style="grey62"))
    else:
        for finding in state.audit.findings[:6]:
            style = _severity_style(finding.severity)
            lines.append(
                Text.assemble(
                    (finding.severity.upper(), style),
                    ("  ", ""),
                    (finding.title, style),
                    ("  ", ""),
                    (finding.detail, "grey62"),
                )
            )
        if state.audit.audit_status:
            lines.extend([Text(), _subheading("auditctl")])
            lines.append(Text(state.audit.audit_status, style="grey70"))
        if state.audit.audit_details:
            detail_keys = ("enabled", "failure", "pid", "rate_limit", "backlog_limit", "lost", "backlog")
            detail_metrics = [
                _metric(key.replace("_", " "), state.audit.audit_details[key], style="grey70")
                for key in detail_keys
                if key in state.audit.audit_details
            ]
            for index in range(0, len(detail_metrics), 3):
                lines.append(_metric_row(*detail_metrics[index:index + 3]))
    return _centered(Group(*lines))


def _render_containers(state: SystemState) -> RenderableType:
    lines: list[Text] = [
        *_section_header("Containers", state.containers.refreshed_at),
        _metric_row(
            _metric("Runtime", state.containers.runtime or "n/a", style="bold white" if state.containers.runtime else "grey62"),
            _metric("Running", str(state.containers.running_count)),
            _metric("Total", str(state.containers.total_count)),
            _metric("Images", str(state.containers.image_count)),
        ),
        Text(),
        _subheading("Workload sample"),
    ]
    if not state.containers.availability.available and state.containers.availability.reason:
        lines.append(Text(state.containers.availability.reason, style="grey62"))
    elif state.containers.containers:
        for container in state.containers.containers[:6]:
            style = "white" if container.state.lower() == "running" else "grey62"
            lines.append(
                _metric_row(
                    _metric(container.name, container.image, style=style),
                    _metric("state", container.status, style="grey70"),
                    _metric("id", container.container_id[:12], style="grey62"),
                )
            )
            if container.ports:
                lines.append(_metric_row(_metric("ports", container.ports, style="grey70")))
    else:
        lines.append(Text("The detected runtime is available but no containers are currently present.", style="grey62"))
    return _centered(Group(*lines))


def format_locked_section(section: str, auth_label: str, message: str) -> RenderableType:
    return _centered(Group(
        Text(f"{section.upper()} LOCKED", style="bold red"),
        Text(),
        Text("This category is behind sudo authentication and collection is deferred until unlock.", style="white"),
        Text.assemble(("STATE ", "grey50"), (auth_label, "bold red" if auth_label != "authenticated" else "bold white")),
        Text.assemble(("DETAIL ", "grey50"), (message or "sudo credentials are required.", "grey62")),
        Text(),
        Text("Press U to unlock this session for privileged categories.", style="grey70"),
        Text("For one-shot output, the CLI scan surface also supports `--unlock`.", style="grey62"),
    ))


def format_section_health_banner(section: str, health: CollectorHealth | None) -> RenderableType | None:
    del section
    if health is None:
        return None

    reason = health.error or health.availability.reason or "No additional collector details were reported."
    last_updated = _timestamp_text(health.last_finished_at or health.last_started_at or datetime.now())

    if health.status == "error":
        return _centered(Group(
            Text("DATA MAY BE STALE", style="bold red"),
            Text.assemble(("LAST UPDATE ", "grey50"), (last_updated, "grey62")),
            Text(reason, style="grey70"),
            Text("Showing the last committed snapshot until a later refresh succeeds.", style="grey62"),
            Text(),
        ))

    if not health.availability.available:
        deferred = (health.availability.reason or "").lower().startswith("collection deferred")
        title = "COLLECTION DEFERRED" if deferred else "BACKEND UNAVAILABLE"
        title_style = "bold white" if deferred else "bold red"
        footer = (
            "Unlock sudo to collect fresh data for this section."
            if deferred
            else "This section is running with reduced capability on the current host."
        )
        return _centered(Group(
            Text(title, style=title_style),
            Text.assemble(("STATUS ", "grey50"), (health.status.upper(), "grey62")),
            Text(reason, style="grey70"),
            Text(footer, style="grey62"),
            Text(),
        ))

    return None


def format_status_bar(
    selected_section: str,
    state: SystemState,
    *,
    selected_category: str | None = None,
    auth_label: str,
    auth_style: str,
    interaction_hint: str | None = None,
    section_locked: bool = False,
) -> RenderableType:
    section_label = (
        selected_section
        if selected_category is None or selected_category == selected_section
        else f"{selected_category} › {selected_section}"
    )
    health_values = list(state.collector_health.values())
    ok_count = sum(
        1
        for health in health_values
        if health.last_completed_status == "ok" and health.availability.available
    )
    running_count = sum(1 for health in health_values if health.status == "running")
    deferred_count = sum(
        1
        for health in health_values
        if health.status == "idle"
        and not health.availability.available
        and (health.availability.reason or "").lower().startswith("collection deferred")
    )
    error_count = sum(
        1
        for health in health_values
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
    alert_count = error_count + critical_findings + failed_services
    lines: list[Text] = [
        _metric_row(
            _metric("Section", section_label, style="bold white"),
            _metric("Updated", _timestamp_text(_status_updated_at(selected_section, state)), style="grey70"),
            _metric("Auth", auth_label, style=auth_style),
            _metric("Alerts", str(alert_count), style="bold red" if alert_count else "white"),
        ),
        _metric_row(
            _metric("Collectors", str(len(health_values))),
            _metric("OK", str(ok_count)),
            _metric("Running", str(running_count), style="bold white" if running_count else "grey62"),
            _metric("Deferred", str(deferred_count), style="bold white" if deferred_count else "grey62"),
            _metric("Errors", str(error_count), style="bold red" if error_count else "white"),
        ),
    ]
    snapshot_line = None if section_locked else _status_snapshot_line(selected_section, state)
    if snapshot_line is not None:
        lines.append(snapshot_line)
    if interaction_hint:
        lines.append(Text.assemble(("HINT ", "grey50"), (interaction_hint, "grey70")))
    return _centered(Group(*lines))


def format_state_section(section: str, state: SystemState) -> RenderableType:
    if section == "Overview":
        return _render_overview(state)
    if section == "System Health":
        return _render_system_health(state)
    if section == "System":
        return _render_system(state)
    if section == "Hardware":
        return _render_hardware(state)
    if section == "Performance":
        return _render_performance(state)
    if section == "Network":
        return _render_network_summary(state)
    if section == "Network Summary":
        return _render_network_summary(state)
    if section == "Interfaces":
        return _render_network(state)
    if section == "Routes & DNS":
        return _render_routes_dns(state)
    if section == "Ports & Connections":
        return _render_ports_connections(state)
    if section == "Firewall":
        return _render_firewall(state)
    if section == "Processes":
        return _render_processes(state)
    if section == "Services":
        return _render_services(state)
    if section == "Logs":
        return _render_logs(state)
    if section == "Security":
        return _render_security_posture(state)
    if section == "Security Posture":
        return _render_security_posture(state)
    if section == "Access & Identity":
        return _render_access_identity(state)
    if section == "Exposure":
        return _render_exposure(state)
    if section == "Sessions":
        return _render_sessions(state)
    if section == "Power":
        return _render_power(state)
    if section == "Kernel":
        return _render_kernel(state)
    if section == "Packages":
        return _render_packages(state)
    if section == "Runtime Backends":
        return _render_runtime_backends(state)
    if section == "Audit":
        return _render_audit(state)
    if section == "Containers":
        return _render_containers(state)
    if section == "Storage":
        return _render_storage(state)
    return _render_events(state)
