from kinatio.collectors.audit import AuditCollector
from kinatio.collectors.logs import LogsCollector
from kinatio.collectors.security import SecurityCollector
from kinatio.config import AppConfig
from kinatio.domain.models import SecurityFinding
from kinatio.execution.subprocess import CommandResult


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


async def test_logs_collector_records_elevated_access_when_sudo_history_succeeds() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["sudo", "--non-interactive", "journalctl", "-n", "1", "-o", "json", "--no-pager"],
                stdout='{"MESSAGE":"hello","SYSLOG_IDENTIFIER":"kernel","PRIORITY":6}',
                stderr="",
                returncode=0,
                executed_with_sudo=True,
            )
        ]
    )

    state = await LogsCollector().collect(runner, AppConfig(log_history_lines=1, max_log_entries=10))

    assert state.collection_access.elevated is True
    assert state.collection_access.partial is False
    assert state.entries[0].message == "hello"
    assert runner.calls[0][1]["prepend_sudo"] is True


async def test_logs_collector_falls_back_to_unprivileged_history_when_sudo_access_fails() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["sudo", "--non-interactive", "journalctl", "-n", "1", "-o", "json", "--no-pager"],
                stdout="",
                stderr="sudo: a password is required",
                returncode=1,
                executed_with_sudo=True,
            ),
            CommandResult(
                command=["journalctl", "-n", "1", "-o", "json", "--no-pager"],
                stdout='{"MESSAGE":"fallback","SYSLOG_IDENTIFIER":"journal","PRIORITY":5}',
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await LogsCollector().collect(runner, AppConfig(log_history_lines=1, max_log_entries=10))

    assert state.collection_access.elevated is False
    assert state.collection_access.partial is True
    assert "accessible journal view" in (state.collection_access.detail or "")
    assert state.entries[0].message == "fallback"
    assert len(runner.calls) == 2
    assert runner.calls[0][1]["prepend_sudo"] is True
    assert runner.calls[1][1].get("prepend_sudo", False) is False


async def test_logs_collector_reports_unavailable_when_elevated_and_fallback_history_fail(monkeypatch) -> None:
    monkeypatch.setattr("kinatio.collectors.logs.detect_log_backend", lambda _precedence: "journalctl")
    runner = StubRunner(
        [
            CommandResult(
                command=["sudo", "--non-interactive", "journalctl", "-n", "1", "-o", "json", "--no-pager"],
                stdout="",
                stderr="sudo: a password is required",
                returncode=1,
                executed_with_sudo=True,
            ),
            CommandResult(
                command=["journalctl", "-n", "1", "-o", "json", "--no-pager"],
                stdout="",
                stderr="journalctl: permission denied",
                returncode=1,
            ),
        ]
    )

    state = await LogsCollector().collect(runner, AppConfig(log_history_lines=1, max_log_entries=10))

    assert state.entries == []
    assert state.collection_access.partial is True
    assert state.availability.available is False
    assert "permission denied" in (state.collection_access.detail or "")


def test_logs_collector_skips_malformed_journal_lines_without_failing() -> None:
    collector = LogsCollector()

    assert collector._parse_journal_line("{not json") is None
    parsed = collector._parse_journal_line('{"MESSAGE":"hello","__REALTIME_TIMESTAMP":"not-a-timestamp"}')

    assert parsed is not None
    assert parsed.message == "hello"


async def test_audit_collector_prefers_elevated_auditctl_status() -> None:
    runner = StubRunner(
        [
            CommandResult(command=["sestatus"], stdout="", stderr="Missing dependency: sestatus", returncode=127, missing_dependency=True),
            CommandResult(command=["aa-status"], stdout="", stderr="Missing dependency: aa-status", returncode=127, missing_dependency=True),
            CommandResult(command=["systemctl", "is-active", "auditd.service"], stdout="", stderr="Missing dependency: systemctl", returncode=127, missing_dependency=True),
            CommandResult(
                command=["sudo", "--non-interactive", "auditctl", "-s"],
                stdout="enabled 1\nbacklog_limit 8192\nbacklog 0\n",
                stderr="",
                returncode=0,
                executed_with_sudo=True,
            ),
        ]
    )

    state = await AuditCollector().collect(runner, AppConfig())

    assert state.audit_status == "enabled 1"
    assert state.audit_details == {"enabled": "1", "backlog_limit": "8192", "backlog": "0"}
    assert state.collection_access.elevated is True
    assert state.collection_access.partial is False
    assert runner.calls[-1][1]["prepend_sudo"] is True


async def test_audit_collector_falls_back_to_unprivileged_auditctl_status_when_sudo_fails() -> None:
    runner = StubRunner(
        [
            CommandResult(command=["sestatus"], stdout="", stderr="Missing dependency: sestatus", returncode=127, missing_dependency=True),
            CommandResult(command=["aa-status"], stdout="", stderr="Missing dependency: aa-status", returncode=127, missing_dependency=True),
            CommandResult(command=["systemctl", "is-active", "auditd.service"], stdout="active\n", stderr="", returncode=0),
            CommandResult(
                command=["sudo", "--non-interactive", "auditctl", "-s"],
                stdout="",
                stderr="sudo: a password is required",
                returncode=1,
                executed_with_sudo=True,
            ),
            CommandResult(
                command=["auditctl", "-s"],
                stdout="enabled 1\nbacklog_limit 8192\n",
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await AuditCollector().collect(runner, AppConfig())

    assert state.auditd_active is True
    assert state.audit_status == "enabled 1"
    assert state.audit_details == {"enabled": "1", "backlog_limit": "8192"}
    assert state.collection_access.elevated is False
    assert state.collection_access.partial is True
    assert "unprivileged status output" in (state.collection_access.detail or "")


async def test_security_collector_distinguishes_sudo_availability_and_session_state(monkeypatch, tmp_path) -> None:
    runner = StubRunner(
        [
            CommandResult(command=["sudo", "-n", "-v"], stdout="", stderr="sudo is already unlocked", returncode=0),
            CommandResult(command=["sudo", "-n", "-l"], stdout="User may run the following commands", stderr="", returncode=0),
        ]
    )
    collector = SecurityCollector()
    monkeypatch.setattr(collector, "_collect_exposed_services", lambda: [])

    state = await collector.collect(runner, AppConfig(anomaly_scan_paths=[tmp_path]))

    assert state.sudo_available is True
    assert state.sudo_authenticated is True
    assert state.sudo_non_interactive is True
    assert state.sudo_configured is True
    assert "bounded posture sampler" in (state.collection_access.detail or "")


async def test_security_collector_reports_missing_sudo(monkeypatch, tmp_path) -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["sudo", "-n", "-v"],
                stdout="",
                stderr="Missing dependency: sudo",
                returncode=127,
                missing_dependency=True,
            ),
            CommandResult(
                command=["sudo", "-n", "-l"],
                stdout="",
                stderr="Missing dependency: sudo",
                returncode=127,
                missing_dependency=True,
            ),
        ]
    )
    collector = SecurityCollector()
    monkeypatch.setattr(collector, "_collect_exposed_services", lambda: [])

    state = await collector.collect(runner, AppConfig(anomaly_scan_paths=[tmp_path]))

    assert state.sudo_available is None
    assert state.sudo_authenticated is False
    assert state.sudo_non_interactive is False
    assert any(finding.title == "sudo unavailable" for finding in state.findings)


async def test_security_collector_reports_locked_sudo_session(monkeypatch, tmp_path) -> None:
    runner = StubRunner(
        [
            CommandResult(command=["sudo", "-n", "-v"], stdout="", stderr="sudo: a password is required", returncode=1),
            CommandResult(command=["sudo", "-n", "-l"], stdout="", stderr="sudo: a password is required", returncode=1),
        ]
    )
    collector = SecurityCollector()
    monkeypatch.setattr(collector, "_collect_exposed_services", lambda: [])

    state = await collector.collect(runner, AppConfig(anomaly_scan_paths=[tmp_path]))

    assert state.sudo_available is True
    assert state.sudo_authenticated is False
    assert state.sudo_non_interactive is False
    assert any(finding.title == "sudo session locked" for finding in state.findings)


async def test_security_collector_offloads_path_scan_to_worker_thread(monkeypatch, tmp_path) -> None:
    runner = StubRunner(
        [
            CommandResult(command=["sudo", "-n", "-v"], stdout="", stderr="sudo is already unlocked", returncode=0),
            CommandResult(command=["sudo", "-n", "-l"], stdout="User may run the following commands", stderr="", returncode=0),
        ]
    )
    collector = SecurityCollector()
    captured: dict[str, object] = {}

    async def fake_to_thread(func, *args):
        captured["func"] = func
        captured["args"] = args
        return [
            SecurityFinding(
                severity="info",
                title="Offloaded scan sentinel",
                detail="Path scanning was delegated to a worker thread.",
            )
        ]

    monkeypatch.setattr(collector, "_collect_exposed_services", lambda: [])
    monkeypatch.setattr("kinatio.collectors.security.asyncio.to_thread", fake_to_thread)

    state = await collector.collect(runner, AppConfig(anomaly_scan_paths=[tmp_path]))

    func = captured["func"]
    assert getattr(func, "__self__", None) is collector
    assert getattr(getattr(func, "__func__", None), "__name__", None) == "_scan_paths"
    assert captured["args"] == ([tmp_path],)
    assert any(finding.title == "Offloaded scan sentinel" for finding in state.findings)
