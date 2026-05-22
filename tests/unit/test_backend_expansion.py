from pathlib import Path

from kinatio.collectors.containers import ContainersCollector
from kinatio.collectors.logs import LogsCollector
from kinatio.collectors.packages import PackagesCollector
from kinatio.collectors.services import ServicesCollector
from kinatio.config import AppConfig
from kinatio.execution.backends import detect_log_backend, detect_service_manager, read_firewall_status
from kinatio.execution.subprocess import CommandResult
from kinatio.runtime.context import detect_runtime_context


class StubRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self.results = results
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    async def run(self, command: list[str], **kwargs: object) -> CommandResult:
        self.calls.append((command, kwargs))
        return self.results.pop(0)

    async def stream_lines(self, command: list[str], **kwargs: object):
        self.calls.append((command, kwargs))
        if False:
            yield ""


def test_detect_service_manager_supports_openrc_and_runit_sentinels() -> None:
    existing_paths = {Path("/run/openrc")}

    backend = detect_service_manager(
        ["systemd", "openrc", "runit", "sysvinit"],
        which=lambda _command: None,
        path_exists=lambda path: path in existing_paths,
    )

    assert backend == "openrc"


def test_detect_log_backend_supports_syslog_paths() -> None:
    existing_paths = {Path("/var/log/messages")}

    backend = detect_log_backend(
        ["journalctl", "syslog", "dmesg"],
        which=lambda _command: None,
        path_exists=lambda path: path in existing_paths,
    )

    assert backend == "syslog"


def test_runtime_context_reports_openrc_and_syslog() -> None:
    existing_paths = {Path("/run/openrc"), Path("/var/log/messages")}

    runtime, backend_status = detect_runtime_context(
        AppConfig(
            service_manager_precedence=["openrc", "systemd"],
            log_backend_precedence=["syslog", "journalctl", "dmesg"],
        ),
        os_release={"ID": "alpine", "PRETTY_NAME": "Alpine Linux"},
        which=lambda _command: None,
        path_exists=lambda path: path in existing_paths,
    )

    assert runtime.init_system == "openrc"
    assert runtime.service_manager == "openrc"
    assert runtime.log_backend == "syslog"
    assert backend_status["service_manager"].reason == "Detected openrc."


async def test_read_firewall_status_uses_nftables_service_state_when_ruleset_requires_privileges() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["systemctl", "is-active", "nftables.service"],
                stdout="active\n",
                stderr="",
                returncode=0,
            ),
            CommandResult(
                command=["nft", "list", "ruleset"],
                stdout="",
                stderr="netlink: Error: cache init failed: Operation not permitted\n",
                returncode=1,
            ),
        ]
    )

    state = await read_firewall_status(runner, "nftables")

    assert state.enabled is True
    assert "active" in state.summary.lower()
    assert "requires elevated privileges" in state.summary.lower()


async def test_read_firewall_status_reports_inactive_nftables_service_as_disabled() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["systemctl", "is-active", "nftables.service"],
                stdout="inactive\n",
                stderr="",
                returncode=3,
            ),
            CommandResult(
                command=["nft", "list", "ruleset"],
                stdout="",
                stderr="netlink: Error: cache init failed: Operation not permitted\n",
                returncode=1,
            ),
        ]
    )

    state = await read_firewall_status(runner, "nftables")

    assert state.enabled is False
    assert "inactive" in state.summary.lower()


async def test_read_firewall_status_keeps_nftables_state_unknown_without_service_signal() -> None:
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
                stdout="",
                stderr="netlink: Error: cache init failed: Operation not permitted\n",
                returncode=1,
            ),
        ]
    )

    state = await read_firewall_status(runner, "nftables")

    assert state.enabled is None
    assert "operation not permitted" in state.summary.lower()


async def test_read_firewall_status_keeps_ufw_state_unknown_when_status_is_unreadable() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["ufw", "status"],
                stdout="",
                stderr="ERROR: problem running iptables: Permission denied\n",
                returncode=1,
            )
        ]
    )

    state = await read_firewall_status(runner, "ufw")

    assert state.enabled is None
    assert "permission denied" in state.summary.lower()


async def test_read_firewall_status_keeps_firewalld_state_unknown_when_state_probe_fails() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["firewall-cmd", "--state"],
                stdout="",
                stderr="Error: DBUS_ERROR\n",
                returncode=1,
            )
        ]
    )

    state = await read_firewall_status(runner, "firewalld")

    assert state.enabled is None
    assert "dbus_error" in state.summary.lower()


async def test_services_collector_parses_openrc_inventory(monkeypatch) -> None:
    monkeypatch.setattr("kinatio.collectors.services.detect_service_manager", lambda _precedence: "openrc")
    runner = StubRunner(
        [
            CommandResult(
                command=["rc-status", "--all"],
                stdout="sshd                                                [  started  ]\ncron                                                [  stopped  ]\n",
                stderr="",
                returncode=0,
            )
        ]
    )

    state = await ServicesCollector().collect(runner, AppConfig(service_manager_precedence=["openrc"]))

    assert state.availability.available is True
    assert [service.name for service in state.services] == ["sshd", "cron"]
    assert state.services[0].active_state == "active"
    assert state.services[1].active_state == "inactive"


async def test_services_collector_parses_sysv_inventory(monkeypatch) -> None:
    monkeypatch.setattr("kinatio.collectors.services.detect_service_manager", lambda _precedence: "sysvinit")
    runner = StubRunner(
        [
            CommandResult(
                command=["service", "--status-all"],
                stdout=" [ + ]  ssh\n [ - ]  cron\n [ ? ]  hwclock.sh\n",
                stderr="",
                returncode=0,
            )
        ]
    )

    state = await ServicesCollector().collect(runner, AppConfig(service_manager_precedence=["sysvinit"]))

    services_by_name = {service.name: service for service in state.services}

    assert set(services_by_name) == {"ssh", "cron", "hwclock.sh"}
    assert services_by_name["ssh"].active_state == "active"
    assert services_by_name["cron"].active_state == "inactive"
    assert services_by_name["hwclock.sh"].active_state == "unknown"


async def test_services_collector_does_not_treat_static_systemd_units_as_enabled(monkeypatch) -> None:
    monkeypatch.setattr("kinatio.collectors.services.detect_service_manager", lambda _precedence: "systemd")
    runner = StubRunner(
        [
            CommandResult(
                command=["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--plain", "--no-legend"],
                stdout="dbus.service loaded active running D-Bus System Message Bus\n",
                stderr="",
                returncode=0,
            ),
            CommandResult(
                command=["systemctl", "list-unit-files", "--type=service", "--no-pager", "--plain", "--no-legend"],
                stdout="dbus.service static\n",
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await ServicesCollector().collect(runner, AppConfig(service_manager_precedence=["systemd"]))

    assert state.manager == "systemd"
    assert state.services[0].unit_file_state == "static"
    assert state.services[0].is_enabled is False


async def test_packages_collector_parses_pacman_updates_and_keeps_architecture_optional(monkeypatch) -> None:
    monkeypatch.setattr(PackagesCollector, "_detect_manager", lambda self, _precedence: "pacman")
    runner = StubRunner(
        [
            CommandResult(command=["pacman", "-Q"], stdout="bash 5.2.037-5\nvim 9.1.001-1\n", stderr="", returncode=0),
            CommandResult(command=["pacman", "-Qu"], stdout="bash 5.2.037-5 -> 5.2.037-6\n", stderr="", returncode=0),
            CommandResult(
                command=["pacman", "-Qi", "bash", "vim"],
                stdout=(
                    "Name            : bash\n"
                    "Version         : 5.2.037-5\n"
                    "Architecture    : x86_64\n"
                    "Description     : The GNU Bourne Again shell\n\n"
                    "Name            : vim\n"
                    "Version         : 9.1.001-1\n"
                    "Architecture    : x86_64\n"
                    "Description     : Vi Improved, a highly configurable text editor\n"
                ),
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await PackagesCollector().collect(runner, AppConfig(max_package_entries=10))

    assert state.manager == "pacman"
    assert state.installed_count == 2
    assert state.update_count == 1
    assert state.entries[0].architecture == "x86_64"
    assert state.entries[0].update_version == "5.2.037-6"
    assert state.entries[0].summary == "The GNU Bourne Again shell"
    assert state.entries[1].update_version is None


async def test_packages_collector_prioritizes_updates_outside_inventory_sample_and_enriches_details(monkeypatch) -> None:
    monkeypatch.setattr(PackagesCollector, "_detect_manager", lambda self, _precedence: "dpkg")
    monkeypatch.setattr(
        "kinatio.collectors.packages.shutil.which",
        lambda command: "/usr/bin/apt" if command == "apt" else "/usr/bin/dpkg-query",
    )
    runner = StubRunner(
        [
            CommandResult(
                command=["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Architecture}\t${binary:Summary}\n"],
                stdout="vim\t9.1.001-1\tamd64\tVi IMproved - enhanced vi editor\n",
                stderr="",
                returncode=0,
            ),
            CommandResult(
                command=["apt", "list", "--upgradable"],
                stdout=(
                    "Listing...\n"
                    "bash/stable 5.2.037-6 amd64 [upgradable from: 5.2.037-5]\n"
                    "bash/stable 5.2.037-6 amd64 [upgradable from: 5.2.037-5]\n"
                ),
                stderr="",
                returncode=0,
            ),
            CommandResult(
                command=["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Architecture}\t${binary:Summary}\n", "bash"],
                stdout="bash\t5.2.037-5\tamd64\tGNU Bourne Again shell\n",
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await PackagesCollector().collect(runner, AppConfig(max_package_entries=1))

    assert state.update_count == 1
    assert [entry.name for entry in state.entries] == ["bash"]
    assert state.entries[0].version == "5.2.037-5"
    assert state.entries[0].update_version == "5.2.037-6"
    assert state.entries[0].summary == "GNU Bourne Again shell"


async def test_containers_collector_captures_ports_from_runtime_inventory(monkeypatch) -> None:
    monkeypatch.setattr(ContainersCollector, "_detect_runtime", lambda self, _precedence: "docker")
    runner = StubRunner(
        [
            CommandResult(
                command=["docker", "ps", "-a"],
                stdout="abc123\tweb\tnginx:stable\trunning\tUp 2 hours\t0.0.0.0:80->80/tcp\n",
                stderr="",
                returncode=0,
            ),
            CommandResult(
                command=["docker", "images"],
                stdout="nginx:stable\nredis:7\n",
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await ContainersCollector().collect(runner, AppConfig(max_container_entries=10))

    assert state.runtime == "docker"
    assert state.running_count == 1
    assert state.image_count == 2
    assert state.containers[0].ports == "0.0.0.0:80->80/tcp"


async def test_logs_collector_parses_dmesg_backend(monkeypatch) -> None:
    monkeypatch.setattr("kinatio.collectors.logs.detect_log_backend", lambda _precedence: "dmesg")
    runner = StubRunner(
        [
            CommandResult(
                command=["sudo", "--non-interactive", "dmesg", "--time-format", "iso", "--color=never"],
                stdout="[2026-05-19T10:11:12+00:00] usb 1-1: new device found\n",
                stderr="",
                returncode=0,
                executed_with_sudo=True,
            )
        ]
    )

    state = await LogsCollector().collect(runner, AppConfig(log_backend_precedence=["dmesg"], log_history_lines=50))

    assert state.collection_access.elevated is True
    assert state.entries[0].source == "kernel"
    assert "new device found" in state.entries[0].message


async def test_logs_collector_parses_syslog_backend(monkeypatch) -> None:
    monkeypatch.setattr("kinatio.collectors.logs.detect_log_backend", lambda _precedence: "syslog")
    monkeypatch.setattr("kinatio.collectors.logs.shutil.which", lambda command: "/usr/bin/tail" if command == "tail" else None)
    monkeypatch.setattr(LogsCollector, "_find_syslog_path", lambda self: Path("/var/log/syslog"))
    runner = StubRunner(
        [
            CommandResult(
                command=["sudo", "--non-interactive", "tail", "-n", "2", "/var/log/syslog"],
                stdout="",
                stderr="sudo: a password is required",
                returncode=1,
                executed_with_sudo=True,
            ),
            CommandResult(
                command=["tail", "-n", "2", "/var/log/syslog"],
                stdout="May 19 10:11:12 host sshd[123]: Accepted publickey for alice\nMay 19 10:11:13 host kernel: link up\n",
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await LogsCollector().collect(runner, AppConfig(log_backend_precedence=["syslog"], log_history_lines=2))

    assert state.collection_access.partial is True
    assert [entry.source for entry in state.entries] == ["sshd", "kernel"]
    assert state.entries[0].message == "Accepted publickey for alice"
