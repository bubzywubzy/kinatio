from pathlib import Path

import pytest

from kinatio.collectors.packages import PackagesCollector
from kinatio.config import AppConfig
from kinatio.execution.backends import detect_firewall_backend, detect_service_manager, read_firewall_status
from kinatio.execution.subprocess import CommandResult


class StubRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self.results = results
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    async def run(self, command: list[str], **kwargs: object) -> CommandResult:
        self.calls.append((command, kwargs))
        return self.results.pop(0)


@pytest.mark.parametrize(
    ("expected_backend", "existing_paths", "available_commands"),
    [
        ("systemd", {Path("/run/systemd/system")}, set()),
        ("openrc", {Path("/run/openrc")}, set()),
        ("runit", {Path("/var/service")}, set()),
        ("sysvinit", set(), {"service"}),
    ],
)
def test_detect_service_manager_supports_each_claimed_backend(
    expected_backend: str,
    existing_paths: set[Path],
    available_commands: set[str],
) -> None:
    backend = detect_service_manager(
        ["systemd", "openrc", "runit", "sysvinit"],
        which=lambda command: f"/usr/bin/{command}" if command in available_commands else None,
        path_exists=lambda path: path in existing_paths,
    )

    assert backend == expected_backend


@pytest.mark.parametrize(
    ("expected_backend", "available_command"),
    [
        ("ufw", "ufw"),
        ("firewalld", "firewall-cmd"),
        ("nftables", "nft"),
    ],
)
def test_detect_firewall_backend_supports_each_claimed_backend(
    expected_backend: str,
    available_command: str,
) -> None:
    backend = detect_firewall_backend(
        ["ufw", "firewalld", "nftables"],
        which=lambda command: f"/usr/bin/{command}" if command == available_command else None,
    )

    assert backend == expected_backend


async def test_read_firewall_status_reports_ufw_as_enabled() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["ufw", "status"],
                stdout="Status: active\nTo                         Action      From\n--                         ------      ----\n22/tcp                     ALLOW       Anywhere\n",
                stderr="",
                returncode=0,
            )
        ]
    )

    state = await read_firewall_status(runner, "ufw")

    assert state.backend == "ufw"
    assert state.enabled is True
    assert "status: active" in state.summary.lower()


async def test_read_firewall_status_reports_firewalld_as_enabled() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["firewall-cmd", "--state"],
                stdout="running\n",
                stderr="",
                returncode=0,
            )
        ]
    )

    state = await read_firewall_status(runner, "firewalld")

    assert state.backend == "firewalld"
    assert state.enabled is True
    assert state.summary == "running"


async def test_read_firewall_status_infers_nftables_enabled_from_ruleset_when_service_probe_is_missing() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["systemctl", "is-active", "nftables.service"],
                stdout="",
                stderr="Missing dependency: systemctl",
                returncode=127,
                missing_dependency=True,
            ),
            CommandResult(
                command=["nft", "list", "ruleset"],
                stdout="table inet filter {\n chain input { type filter hook input priority 0; policy drop; }\n}\n",
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await read_firewall_status(runner, "nftables")

    assert state.backend == "nftables"
    assert state.enabled is True
    assert "policy drop" in state.summary.lower()


async def test_packages_collector_parses_rpm_inventory_updates_and_details(monkeypatch) -> None:
    monkeypatch.setattr(PackagesCollector, "_detect_manager", lambda self, _precedence: "rpm")
    monkeypatch.setattr(
        "kinatio.collectors.packages.shutil.which",
        lambda command: "/usr/bin/dnf" if command == "dnf" else "/usr/bin/rpm",
    )
    runner = StubRunner(
        [
            CommandResult(
                command=["rpm", "-qa", "--qf", r"%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SUMMARY}\n"],
                stdout=(
                    "bash\t5.2.037-5\tx86_64\tGNU Bourne Again shell\n"
                    "vim\t9.1.001-1\tx86_64\tVi Improved\n"
                ),
                stderr="",
                returncode=0,
            ),
            CommandResult(
                command=["dnf", "-q", "check-update"],
                stdout="bash.x86_64 5.2.037-6 updates\n",
                stderr="",
                returncode=100,
            ),
            CommandResult(
                command=["rpm", "-q", "--qf", r"%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SUMMARY}\n", "bash", "vim"],
                stdout=(
                    "bash\t5.2.037-5\tx86_64\tGNU Bourne Again shell\n"
                    "vim\t9.1.001-1\tx86_64\tVi Improved\n"
                ),
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await PackagesCollector().collect(runner, AppConfig(max_package_entries=10))

    assert state.manager == "rpm"
    assert state.installed_count == 2
    assert state.update_count == 1
    assert state.entries[0].name == "bash"
    assert state.entries[0].architecture == "x86_64"
    assert state.entries[0].update_version == "5.2.037-6"
    assert state.entries[0].summary == "GNU Bourne Again shell"
    assert state.entries[1].name == "vim"
    assert state.entries[1].update_version is None


async def test_packages_collector_parses_apk_inventory_and_updates(monkeypatch) -> None:
    monkeypatch.setattr(PackagesCollector, "_detect_manager", lambda self, _precedence: "apk")
    runner = StubRunner(
        [
            CommandResult(
                command=["apk", "info", "-v"],
                stdout="busybox-1.36.1-r2\nopenssl-3.3.2-r0\n",
                stderr="",
                returncode=0,
            ),
            CommandResult(
                command=["apk", "version", "-l", "<"],
                stdout="openssl 3.3.2-r1\n",
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await PackagesCollector().collect(runner, AppConfig(max_package_entries=10))

    assert state.manager == "apk"
    assert state.installed_count == 2
    assert state.update_count == 1
    assert state.entries[0].name == "openssl"
    assert state.entries[0].version == "3.3.2-r0"
    assert state.entries[0].update_version == "3.3.2-r1"
    assert state.entries[1].name == "busybox"
    assert state.entries[1].version == "1.36.1-r2"
