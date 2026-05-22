"""Runtime capability detection for distro-aware orchestration."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from kinatio.config import AppConfig
from kinatio.domain.models import AvailabilityInfo, RuntimeContext, utc_now
from kinatio.execution.backends import detect_firewall_backend, detect_log_backend, detect_service_manager

CommandLocator = Callable[[str], str | None]
PathChecker = Callable[[Path], bool]

OS_RELEASE_PATHS = (Path("/etc/os-release"), Path("/usr/lib/os-release"))
PACKAGE_MANAGER_COMMANDS = {
    "dpkg": "dpkg-query",
    "rpm": "rpm",
    "pacman": "pacman",
    "apk": "apk",
}
SERVICE_MANAGER_COMMANDS = {
    "systemd": "systemctl",
    "openrc": "rc-service",
    "runit": "sv",
    "sysvinit": "service",
}
SECURITY_BACKEND_COMMANDS = {
    "selinux": ("getenforce", "sestatus"),
    "apparmor": ("aa-status",),
    "sudo": ("sudo",),
}
CONTAINER_RUNTIME_COMMANDS = {
    "docker": "docker",
    "podman": "podman",
}


def detect_runtime_context(
    config: AppConfig,
    *,
    os_release: Mapping[str, str] | None = None,
    which: CommandLocator = shutil.which,
    path_exists: PathChecker = Path.exists,
) -> tuple[RuntimeContext, dict[str, AvailabilityInfo]]:
    """Detect the host runtime context and backend availability."""

    release = dict(os_release) if os_release is not None else _read_os_release(path_exists=path_exists)
    distro_name = release.get("PRETTY_NAME") or release.get("NAME")
    distro_id = (release.get("ID") or "").strip().lower() or None
    distro_like = [value for value in (release.get("ID_LIKE") or "").split() if value]

    service_manager = detect_service_manager(config.service_manager_precedence, which=which, path_exists=path_exists)
    runtime = RuntimeContext(
        refreshed_at=utc_now(),
        distro_id=distro_id,
        distro_name=distro_name,
        distro_version=release.get("VERSION_ID") or None,
        distro_like=distro_like,
        init_system=service_manager,
        service_manager=service_manager,
        log_backend=detect_log_backend(config.log_backend_precedence, which=which, path_exists=path_exists),
        package_manager=_detect_named_backend(config.package_manager_precedence, PACKAGE_MANAGER_COMMANDS, which),
        firewall_backend=detect_firewall_backend(config.firewall_backend_precedence, which=which),
        security_backend=_detect_security_backend(config.security_backend_precedence, which=which, path_exists=path_exists),
        container_runtime=_detect_named_backend(config.container_runtime_precedence, CONTAINER_RUNTIME_COMMANDS, which),
        availability=AvailabilityInfo(
            available=bool(distro_id or distro_name),
            reason=None if (distro_id or distro_name) else "Unable to resolve Linux distribution metadata from os-release.",
            dependency="os-release" if (distro_id or distro_name) else None,
        ),
    )
    return runtime, build_backend_status(runtime)


def build_backend_status(runtime: RuntimeContext) -> dict[str, AvailabilityInfo]:
    """Build user-visible backend availability from the detected runtime context."""

    distro_label = runtime.distro_name or runtime.distro_id
    return {
        "distro": _available_info(distro_label, "Linux distribution metadata was not detected."),
        "init_system": _available_info(runtime.init_system, "No supported init system was detected."),
        "service_manager": _available_info(runtime.service_manager, "No supported service manager was detected."),
        "log_backend": _available_info(runtime.log_backend, "No supported log backend was detected."),
        "package_manager": _available_info(runtime.package_manager, "No supported package manager was detected."),
        "firewall_backend": _available_info(runtime.firewall_backend, "No supported firewall backend was detected."),
        "security_backend": _available_info(runtime.security_backend, "No supported security backend was detected."),
        "container_runtime": _available_info(runtime.container_runtime, "No supported container runtime was detected."),
    }


def _available_info(value: str | None, unavailable_reason: str) -> AvailabilityInfo:
    if value:
        return AvailabilityInfo(available=True, reason=f"Detected {value}.")
    return AvailabilityInfo(available=False, reason=unavailable_reason)


def _read_os_release(*, path_exists: PathChecker) -> dict[str, str]:
    for path in OS_RELEASE_PATHS:
        if not path_exists(path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parsed = _parse_os_release(content)
        if parsed:
            return parsed
    return {}


def _parse_os_release(content: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key] = value.strip().strip('"').strip("'")
    return parsed


def _detect_named_backend(
    precedence: list[str],
    commands: Mapping[str, str],
    which: CommandLocator,
) -> str | None:
    for backend in precedence:
        command = commands.get(backend)
        if command and which(command):
            return backend
    return None


def _detect_security_backend(
    precedence: list[str],
    *,
    which: CommandLocator,
    path_exists: PathChecker,
) -> str | None:
    sentinel_paths = {
        "selinux": (Path("/sys/fs/selinux"), Path("/etc/selinux/config")),
        "apparmor": (Path("/sys/module/apparmor"), Path("/etc/apparmor")),
    }
    for backend in precedence:
        if any(path_exists(path) for path in sentinel_paths.get(backend, ())):
            return backend
        for command in SECURITY_BACKEND_COMMANDS.get(backend, ()):  # type: ignore[arg-type]
            if which(command):
                return backend
    return None