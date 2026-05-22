"""Normalized domain models for system state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class AvailabilityInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = True
    reason: str | None = None
    dependency: str | None = None


class CollectionAccessInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requires_auth: bool = False
    elevated: bool = False
    partial: bool = False
    detail: str | None = None


class CollectorHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collector: str
    status: Literal["idle", "running", "ok", "error"] = "idle"
    last_completed_status: Literal["idle", "ok", "error"] = "idle"
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    duration_ms: float | None = None
    error: str | None = None
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class CPUCoreInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    percent: float


class CPUInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logical_cores: int = 0
    physical_cores: int | None = None
    model_name: str | None = None
    architecture: str | None = None
    frequency_current_mhz: float | None = None
    frequency_max_mhz: float | None = None
    load_percent: float = 0.0
    per_core: list[CPUCoreInfo] = Field(default_factory=list)


class MemoryInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_bytes: int = 0
    available_bytes: int = 0
    used_bytes: int = 0
    percent: float = 0.0
    swap_total_bytes: int = 0
    swap_used_bytes: int = 0
    swap_percent: float = 0.0


class DeviceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    identifier: str
    description: str


class GPUInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    vendor: str | None = None
    bus_id: str | None = None
    driver: str | None = None
    backend: str | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    utilization_percent: float | None = None
    temperature_celsius: float | None = None
    workload_source: str | None = None
    workloads: list[GPUWorkloadInfo] = Field(default_factory=list)


class GPUWorkloadInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pid: int | None = None
    process_name: str
    command: str | None = None
    gpu_memory_bytes: int | None = None
    kind: str | None = None


class HardwareState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    cpu: CPUInfo = Field(default_factory=CPUInfo)
    memory: MemoryInfo = Field(default_factory=MemoryInfo)
    gpus: list[GPUInfo] = Field(default_factory=list)
    pci_devices: list[DeviceInfo] = Field(default_factory=list)
    usb_devices: list[DeviceInfo] = Field(default_factory=list)
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class OSState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    hostname: str = ""
    fqdn: str = ""
    kernel_release: str = ""
    kernel_version: str = ""
    uptime_seconds: float = 0.0
    load_average: tuple[float, float, float] = (0.0, 0.0, 0.0)
    sysctl_values: dict[str, str] = Field(default_factory=dict)
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class ProcessEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pid: int
    name: str
    username: str | None = None
    status: str | None = None
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    rss_bytes: int = 0
    command: str = ""


class ProcessesState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    total_processes: int = 0
    entries: list[ProcessEntry] = Field(default_factory=list)
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class NetworkAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str
    address: str
    netmask: str | None = None
    broadcast: str | None = None


class NetworkInterface(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    is_up: bool = False
    speed_mbps: int | None = None
    mtu: int | None = None
    mac_address: str | None = None
    addresses: list[NetworkAddress] = Field(default_factory=list)
    rx_bytes: int = 0
    tx_bytes: int = 0


class RouteEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: str
    gateway: str | None = None
    device: str | None = None
    protocol: str | None = None
    metric: int | None = None
    scope: str | None = None


class DnsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    servers: list[str] = Field(default_factory=list)
    search: list[str] = Field(default_factory=list)
    source: str = "unknown"


class PortEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: str
    local_address: str
    local_port: int
    pid: int | None = None
    process_name: str | None = None


class ConnectionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: str
    status: str
    local_address: str
    local_port: int
    remote_address: str | None = None
    remote_port: int | None = None
    pid: int | None = None


class FirewallState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: str | None = None
    enabled: bool | None = None
    summary: str = ""
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class NetworkState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    interfaces: list[NetworkInterface] = Field(default_factory=list)
    routes: list[RouteEntry] = Field(default_factory=list)
    dns: DnsConfig = Field(default_factory=DnsConfig)
    listening_ports: list[PortEntry] = Field(default_factory=list)
    active_connections: list[ConnectionEntry] = Field(default_factory=list)
    firewall: FirewallState = Field(default_factory=FirewallState)
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class ServiceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    load_state: str = "unknown"
    active_state: str = "unknown"
    sub_state: str = "unknown"
    description: str = ""
    unit_file_state: str = "unknown"
    is_failed: bool = False
    is_enabled: bool = False


class ServicesState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    manager: str | None = None
    services: list[ServiceEntry] = Field(default_factory=list)
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class LogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(default_factory=utc_now)
    source: str = "journal"
    unit: str | None = None
    priority: str | None = None
    message: str = ""


class LogsState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    entries: list[LogEntry] = Field(default_factory=list)
    live_enabled: bool = True
    collection_access: CollectionAccessInfo = Field(
        default_factory=lambda: CollectionAccessInfo(requires_auth=True)
    )
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class StorageMount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: str
    mount_point: str
    filesystem: str
    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    inode_used_percent: float | None = None
    options: str = ""


class DiskDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    model: str | None = None
    serial: str | None = None
    size_bytes: int | None = None
    transport: str | None = None
    smart_available: bool = False
    smart_health: str | None = None
    temperature_celsius: float | None = None


class StorageState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    mounts: list[StorageMount] = Field(default_factory=list)
    disks: list[DiskDevice] = Field(default_factory=list)
    io_counters: dict[str, dict[str, int | float]] = Field(default_factory=dict)
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class SecurityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["info", "warning", "critical"] = "info"
    title: str
    detail: str
    path: str | None = None


class SecurityState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    sudo_available: bool | None = None
    sudo_authenticated: bool = False
    sudo_non_interactive: bool = False
    sudo_configured: bool = False
    sudo_summary: str = ""
    users: list[str] = Field(default_factory=list)
    groups: dict[str, list[str]] = Field(default_factory=dict)
    findings: list[SecurityFinding] = Field(default_factory=list)
    exposed_services: list[PortEntry] = Field(default_factory=list)
    collection_access: CollectionAccessInfo = Field(
        default_factory=lambda: CollectionAccessInfo(requires_auth=True)
    )
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class SessionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    terminal: str | None = None
    host: str | None = None
    started_at: datetime | None = None
    pid: int | None = None


class LoginHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    terminal: str | None = None
    host: str | None = None
    summary: str


class SessionsState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    current_sessions: list[SessionEntry] = Field(default_factory=list)
    recent_logins: list[LoginHistoryEntry] = Field(default_factory=list)
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class ThermalSensor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    label: str
    current_celsius: float
    high_celsius: float | None = None
    critical_celsius: float | None = None


class FanSensor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    label: str
    rpm: int


class PowerState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    battery_present: bool = False
    battery_percent: float | None = None
    power_plugged: bool | None = None
    seconds_left: int | None = None
    thermal_sensors: list[ThermalSensor] = Field(default_factory=list)
    fan_sensors: list[FanSensor] = Field(default_factory=list)
    cpu_governors: dict[str, int] = Field(default_factory=dict)
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class PackageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    architecture: str | None = None
    update_version: str | None = None
    summary: str | None = None


class PackagesState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    manager: str | None = None
    installed_count: int = 0
    update_count: int | None = None
    entries: list[PackageEntry] = Field(default_factory=list)
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class AuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["info", "warning", "critical"] = "info"
    title: str
    detail: str


class AuditState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    selinux_enabled: bool | None = None
    selinux_mode: str | None = None
    apparmor_enabled: bool | None = None
    apparmor_profiles_loaded: int | None = None
    auditd_active: bool | None = None
    audit_status: str | None = None
    audit_details: dict[str, str] = Field(default_factory=dict)
    findings: list[AuditFinding] = Field(default_factory=list)
    collection_access: CollectionAccessInfo = Field(
        default_factory=lambda: CollectionAccessInfo(requires_auth=True)
    )
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class ContainerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container_id: str
    name: str
    image: str
    state: str
    status: str
    ports: str | None = None


class ContainersState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    runtime: str | None = None
    running_count: int = 0
    total_count: int = 0
    image_count: int = 0
    containers: list[ContainerEntry] = Field(default_factory=list)
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class RuntimeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_at: datetime = Field(default_factory=utc_now)
    distro_id: str | None = None
    distro_name: str | None = None
    distro_version: str | None = None
    distro_like: list[str] = Field(default_factory=list)
    init_system: str | None = None
    service_manager: str | None = None
    log_backend: str | None = None
    package_manager: str | None = None
    firewall_backend: str | None = None
    security_backend: str | None = None
    container_runtime: str | None = None
    availability: AvailabilityInfo = Field(default_factory=AvailabilityInfo)


class EventEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(default_factory=utc_now)
    source: str
    severity: Literal["info", "warning", "error"] = "info"
    title: str
    details: dict[str, Any] = Field(default_factory=dict)


class SystemState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(default_factory=utc_now)
    hardware: HardwareState = Field(default_factory=HardwareState)
    os_state: OSState = Field(default_factory=OSState)
    processes: ProcessesState = Field(default_factory=ProcessesState)
    network: NetworkState = Field(default_factory=NetworkState)
    services: ServicesState = Field(default_factory=ServicesState)
    logs: LogsState = Field(default_factory=LogsState)
    storage: StorageState = Field(default_factory=StorageState)
    security: SecurityState = Field(default_factory=SecurityState)
    sessions: SessionsState = Field(default_factory=SessionsState)
    power: PowerState = Field(default_factory=PowerState)
    packages: PackagesState = Field(default_factory=PackagesState)
    audit: AuditState = Field(default_factory=AuditState)
    containers: ContainersState = Field(default_factory=ContainersState)
    runtime: RuntimeContext = Field(default_factory=RuntimeContext)
    events: list[EventEntry] = Field(default_factory=list)
    collector_health: dict[str, CollectorHealth] = Field(default_factory=dict)
    backend_status: dict[str, AvailabilityInfo] = Field(default_factory=dict)
