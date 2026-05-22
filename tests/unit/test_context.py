from pathlib import Path

from kinatio.config import AppConfig
from kinatio.runtime.context import detect_runtime_context


def test_detect_runtime_context_prefers_configured_backends() -> None:
    existing_paths = {
        Path("/run/systemd/system"),
        Path("/sys/module/apparmor"),
    }

    def fake_which(command: str) -> str | None:
        available = {
            "systemctl",
            "journalctl",
            "pacman",
            "podman",
            "firewall-cmd",
            "aa-status",
        }
        return f"/usr/bin/{command}" if command in available else None

    runtime, backend_status = detect_runtime_context(
        AppConfig(
            package_manager_precedence=["pacman", "dpkg"],
            container_runtime_precedence=["podman", "docker"],
            firewall_backend_precedence=["firewalld", "ufw", "nftables"],
            service_manager_precedence=["systemd", "openrc"],
            log_backend_precedence=["journalctl", "syslog", "dmesg"],
            security_backend_precedence=["apparmor", "selinux", "sudo"],
        ),
        os_release={
            "ID": "arch",
            "PRETTY_NAME": "Arch Linux",
            "VERSION_ID": "rolling",
            "ID_LIKE": "archlinux",
        },
        which=fake_which,
        path_exists=lambda path: path in existing_paths,
    )

    assert runtime.distro_id == "arch"
    assert runtime.distro_name == "Arch Linux"
    assert runtime.init_system == "systemd"
    assert runtime.service_manager == "systemd"
    assert runtime.log_backend == "journalctl"
    assert runtime.package_manager == "pacman"
    assert runtime.firewall_backend == "firewalld"
    assert runtime.security_backend == "apparmor"
    assert runtime.container_runtime == "podman"
    assert backend_status["service_manager"].available is True
    assert backend_status["firewall_backend"].reason == "Detected firewalld."


def test_detect_runtime_context_reports_missing_backends() -> None:
    runtime, backend_status = detect_runtime_context(
        AppConfig(),
        os_release={
            "ID": "debian",
            "PRETTY_NAME": "Debian GNU/Linux 12",
            "VERSION_ID": "12",
        },
        which=lambda _command: None,
        path_exists=lambda _path: False,
    )

    assert runtime.distro_id == "debian"
    assert runtime.service_manager is None
    assert runtime.log_backend is None
    assert runtime.package_manager is None
    assert backend_status["distro"].available is True
    assert backend_status["log_backend"].available is False
    assert backend_status["package_manager"].available is False


def test_detect_runtime_context_supports_selinux_and_docker_fallback() -> None:
    existing_paths = {
        Path("/etc/selinux/config"),
    }

    def fake_which(command: str) -> str | None:
        available = {
            "docker",
            "rpm",
            "ufw",
            "journalctl",
            "systemctl",
        }
        return f"/usr/bin/{command}" if command in available else None

    runtime, backend_status = detect_runtime_context(
        AppConfig(
            package_manager_precedence=["rpm", "dpkg"],
            container_runtime_precedence=["docker", "podman"],
            firewall_backend_precedence=["ufw", "firewalld", "nftables"],
            service_manager_precedence=["systemd", "openrc"],
            log_backend_precedence=["journalctl", "syslog", "dmesg"],
            security_backend_precedence=["selinux", "apparmor", "sudo"],
        ),
        os_release={
            "ID": "fedora",
            "PRETTY_NAME": "Fedora Linux",
            "VERSION_ID": "42",
        },
        which=fake_which,
        path_exists=lambda path: path in existing_paths,
    )

    assert runtime.service_manager == "systemd"
    assert runtime.log_backend == "journalctl"
    assert runtime.package_manager == "rpm"
    assert runtime.firewall_backend == "ufw"
    assert runtime.security_backend == "selinux"
    assert runtime.container_runtime == "docker"
    assert backend_status["security_backend"].reason == "Detected selinux."
    assert backend_status["container_runtime"].reason == "Detected docker."


def test_detect_runtime_context_falls_back_to_sudo_security_backend() -> None:
    runtime, backend_status = detect_runtime_context(
        AppConfig(
            security_backend_precedence=["apparmor", "selinux", "sudo"],
        ),
        os_release={
            "ID": "debian",
            "PRETTY_NAME": "Debian GNU/Linux 12",
            "VERSION_ID": "12",
        },
        which=lambda command: f"/usr/bin/{command}" if command == "sudo" else None,
        path_exists=lambda _path: False,
    )

    assert runtime.security_backend == "sudo"
    assert backend_status["security_backend"].reason == "Detected sudo."