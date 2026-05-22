import argparse
from pathlib import Path

import pytest

from kinatio.cli.main import CLIError, _handle_sections, _persist_cache_snapshot, _write_output_file, build_parser
from kinatio.domain.models import AuditFinding, AuditState, CollectionAccessInfo, LogEntry, LogsState, SecurityFinding, SecurityState, SystemState


class StubCache:
    def __init__(self) -> None:
        self.saved_state: SystemState | None = None

    def save(self, state: SystemState) -> None:
        self.saved_state = state


class StubRuntime:
    def __init__(self) -> None:
        self.cache = StubCache()


def test_cli_parser_accepts_canonical_scan_commands() -> None:
    args = build_parser().parse_args(["scan", "system", "network", "--json", "--unlock"])

    assert args.command == "scan"
    assert args.targets == ["system", "network"]
    assert args.json is True
    assert args.unlock is True


def test_cli_parser_accepts_scan_all_with_export() -> None:
    args = build_parser().parse_args(["scan", "all", "--output", "report.json"])

    assert args.command == "scan"
    assert args.targets == ["all"]
    assert args.output == Path("report.json")


def test_cli_parser_accepts_status_command() -> None:
    args = build_parser().parse_args(["status", "--json"])

    assert args.command == "status"
    assert args.json is True


def test_cli_parser_only_exposes_observe_only_subcommands() -> None:
    parser = build_parser()
    subparsers_action = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )

    assert set(subparsers_action.choices) == {"scan", "sections", "status", "tui"}


def test_cli_parser_accepts_firewall_scan_in_observe_only_surface() -> None:
    args = build_parser().parse_args(["scan", "firewall", "--json"])

    assert args.command == "scan"
    assert args.targets == ["firewall"]
    assert args.json is True


def test_cli_parser_rejects_removed_service_action_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["service", "restart", "sshd.service", "--yes"])


def test_cli_parser_rejects_removed_process_action_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["process", "terminate", "123", "--signal", "kill", "--yes"])


def test_cli_parser_rejects_removed_firewall_action_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["firewall", "enable", "--yes"])


def test_cli_parser_accepts_logs_follow_scan() -> None:
    args = build_parser().parse_args(["scan", "logs", "--follow", "--unlock"])

    assert args.command == "scan"
    assert args.targets == ["logs"]
    assert args.follow is True
    assert args.unlock is True


def test_cli_parser_rejects_removed_direct_section_aliases() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["system", "--cached"])


def test_cli_parser_rejects_removed_legacy_action_namespace() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["action", "terminate-process", "123", "--yes"])


def test_cli_root_help_prioritizes_canonical_commands_over_aliases() -> None:
    help_text = build_parser().format_help()

    assert "scan" in help_text
    assert "sections" in help_text
    assert "status" in help_text
    assert "tui" in help_text
    assert "service restart" not in help_text
    assert "process terminate" not in help_text
    assert "firewall enable" not in help_text
    assert "safe action" not in help_text
    assert "Compatibility alias" not in help_text
    assert "restart-service" not in help_text
    assert "terminate-process" not in help_text
    assert "toggle-firewall" not in help_text


def test_scan_help_explicitly_marks_follow_as_logs_only() -> None:
    parser = build_parser()
    subparsers_action = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    scan_help = subparsers_action.choices["scan"].format_help()

    assert "Follow live updates for the Logs section only." in scan_help


async def test_sections_command_lists_descriptions_and_privilege_markers(capsys) -> None:
    exit_code = await _handle_sections(argparse.Namespace())
    captured = capsys.readouterr()
    output = captured.out.lower()

    assert exit_code == 0
    assert "preferred non-interactive reporting surface" in output
    assert "firewall" in output
    assert "logs" in output
    assert "category: administration" in output
    assert "privileged" in output
    assert "follow" in output
    assert "preferred: kinatio scan logs" in output
    assert "preferred: kinatio scan firewall" in output
    assert "available scan sections" in output
    assert "compatibility" not in output
    assert "safe service actions" not in output
    assert "safe process actions" not in output
    assert "safe firewall actions" not in output


def test_write_output_file_creates_restrictive_permissions(tmp_path: Path) -> None:
    output_path = tmp_path / "report.json"

    _write_output_file(output_path, '{"ok": true}\n')

    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == '{"ok": true}\n'
    assert output_path.stat().st_mode & 0o777 == 0o600


def test_write_output_file_raises_clierror_and_cleans_temp_file_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "report.json"

    def fail_replace(self: Path, target: Path) -> Path:
        del self, target
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(CLIError, match="unable to write output file"):
        _write_output_file(output_path, "hello")

    assert not output_path.exists()
    assert list(tmp_path.glob(f".{output_path.name}*.tmp")) == []


def test_persist_cache_snapshot_redacts_privileged_data_before_writing() -> None:
    runtime = StubRuntime()
    state = SystemState(
        logs=LogsState(
            entries=[LogEntry(message="cached privileged log line")],
            live_enabled=True,
            collection_access=CollectionAccessInfo(requires_auth=True, elevated=True, detail="Collected through sudo."),
        ),
        security=SecurityState(
            sudo_available=True,
            sudo_authenticated=True,
            sudo_non_interactive=True,
            sudo_configured=True,
            sudo_summary="sudo already unlocked",
            users=["alice"],
            findings=[SecurityFinding(severity="critical", title="cached finding", detail="secret")],
            collection_access=CollectionAccessInfo(requires_auth=True, elevated=True, detail="Collected through sudo."),
        ),
        audit=AuditState(
            audit_status="enabled 1",
            findings=[AuditFinding(severity="warning", title="cached audit", detail="secret")],
            collection_access=CollectionAccessInfo(requires_auth=True, elevated=True, detail="Collected through sudo."),
        ),
    )

    _persist_cache_snapshot(runtime, state)  # type: ignore[arg-type]

    assert runtime.cache.saved_state is not None
    assert runtime.cache.saved_state.logs.entries == []
    assert runtime.cache.saved_state.security.users == []
    assert runtime.cache.saved_state.audit.findings == []
