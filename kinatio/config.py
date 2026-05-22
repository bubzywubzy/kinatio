"""Application configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class AppConfig(BaseModel):
    """Runtime configuration for the Kinatio application."""

    model_config = ConfigDict(frozen=True)

    cache_path: Path = Field(default_factory=lambda: Path.home() / ".cache" / "kinatio" / "state.json")
    ui_refresh_interval: float = 1.0
    interactive_auto_refresh_min_interval: float = 8.0
    auth_refresh_interval: float = 10.0
    privileged_auth_poll_interval: float = 30.0
    collector_failure_backoff_max_interval: float = 60.0
    stream_failure_backoff_base_interval: float = 5.0
    stream_failure_backoff_max_interval: float = 30.0
    log_history_lines: int = 150
    max_log_entries: int = 500
    suppress_known_log_noise_by_default: bool = True
    show_ascii_header: bool = True
    ascii_header_min_width: int = 72
    log_noise_patterns: list[str] = Field(
        default_factory=lambda: [
            r"window\.tile is deprecated:\s*use tile\.manage\(\) instead",
            r"workspace\.tilingForScreen\(\) is deprecated:\s*use workspace\.rootTile\(\) instead",
            r"window::os::wayland::pointer\s*>\s*set_cursor:\s*Unable to set cursor to hand:\s*cursor not found",
        ]
    )
    max_process_entries: int = 200
    max_session_entries: int = 24
    max_login_history: int = 12
    max_package_entries: int = 40
    max_container_entries: int = 20
    max_audit_findings: int = 20
    refresh_intervals: dict[str, float] = Field(
        default_factory=lambda: {
            "hardware": 10.0,
            "os_state": 10.0,
            "processes": 4.0,
            "network": 6.0,
            "services": 12.0,
            "storage": 15.0,
            "security": 30.0,
            "sessions": 20.0,
            "power": 12.0,
            "packages": 180.0,
            "audit": 45.0,
            "containers": 20.0,
            "logs": 20.0,
        }
    )
    sysctl_keys: list[str] = Field(
        default_factory=lambda: [
            "kernel.hostname",
            "kernel.domainname",
            "kernel.pid_max",
            "net.ipv4.ip_forward",
            "vm.swappiness",
        ]
    )
    firewall_backend_precedence: list[str] = Field(
        default_factory=lambda: ["ufw", "firewalld", "nftables"]
    )
    service_manager_precedence: list[str] = Field(
        default_factory=lambda: ["systemd", "openrc", "runit", "sysvinit"]
    )
    log_backend_precedence: list[str] = Field(
        default_factory=lambda: ["journalctl", "syslog", "dmesg"]
    )
    security_backend_precedence: list[str] = Field(
        default_factory=lambda: ["selinux", "apparmor", "sudo"]
    )
    package_manager_precedence: list[str] = Field(
        default_factory=lambda: ["dpkg", "rpm", "pacman", "apk"]
    )
    container_runtime_precedence: list[str] = Field(default_factory=lambda: ["docker", "podman"])
    anomaly_scan_paths: list[Path] = Field(default_factory=lambda: [Path("/etc"), Path("/usr/local/bin")])
    allowed_service_pattern: str = r"^[a-zA-Z0-9_.@-]+(?:\.service)?$"
    allowed_process_signals: list[str] = Field(default_factory=lambda: ["TERM", "KILL", "HUP"])


DEFAULT_CONFIG = AppConfig()
