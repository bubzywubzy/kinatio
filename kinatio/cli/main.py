"""Command-line interface for Kinatio."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import io
import json
import os
import tempfile
from collections.abc import Sequence
from inspect import isawaitable
from pathlib import Path
from typing import Any

from rich.console import Console

from kinatio.domain.models import AvailabilityInfo, CollectorHealth, LogEntry, SystemState
from kinatio.execution.auth import SudoAuthState
from kinatio.sections import (
    DEFERRED_SUBSYSTEMS,
    FOLLOWABLE_SECTIONS,
    PRIVILEGED_SECTIONS,
    SECTION_COMMANDS,
    SECTION_DESCRIPTIONS,
    SECTIONS,
    get_section_category,
    get_section_policy,
    section_payload_data,
)
from kinatio.runtime.bootstrap import (
    RuntimeServices,
    create_runtime_services,
    prime_runtime_store,
    redact_locked_privileged_state,
    state_for_persistence,
)
from kinatio.ui.layout import (
    format_locked_section,
    format_section_health_banner,
    format_state_section,
    format_status_bar,
)


class CLIError(RuntimeError):
    """Raised for user-facing CLI failures."""


class CLIContext:
    """Mutable CLI runtime state shared with collection-gate callbacks."""

    def __init__(self) -> None:
        self.auth_state = SudoAuthState.locked("Checking sudo status.")


def build_parser() -> argparse.ArgumentParser:
    """Build the Kinatio CLI parser."""

    parser = argparse.ArgumentParser(
        prog="kinatio",
        description=(
            "Inspect Kinatio system sections, export scan data, and verify host state "
            "from the command line."
        ),
        epilog="Use `kinatio sections` for section descriptions, privilege markers, and scan target discovery.",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    sections_parser = subparsers.add_parser("sections", help="List the available CLI command families and section aliases.")
    sections_parser.set_defaults(handler=_handle_sections)

    tui_parser = subparsers.add_parser("tui", help="Launch the Textual interface explicitly.")
    tui_parser.set_defaults(handler=_handle_tui_passthrough)

    status_parser = subparsers.add_parser("status", help="Show runtime, backend, and collector health status.")
    _add_output_arguments(status_parser)
    status_parser.set_defaults(handler=_handle_status)

    scan_parser = subparsers.add_parser("scan", help="Collect and render one or more sections.")
    scan_parser.add_argument(
        "targets",
        nargs="+",
        metavar="section",
        help="Section names to scan (for example: system network storage) or `all`.",
    )
    _add_scan_arguments(scan_parser, allow_unlock=True, allow_follow=True)
    scan_parser.set_defaults(handler=_handle_scan)

    return parser


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output.")
    parser.add_argument("--output", type=Path, help="Write output to a file instead of stdout.")


def _add_scan_arguments(
    parser: argparse.ArgumentParser,
    *,
    allow_unlock: bool,
    allow_follow: bool,
) -> None:
    parser.add_argument("--cached", action="store_true", help="Render the cached snapshot without refreshing collectors first.")
    _add_output_arguments(parser)
    if allow_unlock:
        parser.add_argument(
            "--unlock",
            action="store_true",
            help="Prompt for sudo so deferred privileged data can be collected before rendering.",
        )
    if allow_follow:
        parser.add_argument("--follow", action="store_true", help="Follow live updates for the Logs section only.")


async def run_cli(argv: Sequence[str] | None = None) -> int:
    """Execute the CLI and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return await args.handler(args)
    except CLIError as exc:
        print(f"kinatio: {exc}")
        return 2
    except KeyboardInterrupt:
        print("kinatio: interrupted")
        return 130


def main(argv: Sequence[str] | None = None) -> int:
    """Synchronous CLI entrypoint."""

    return asyncio.run(run_cli(argv))


async def _handle_sections(args: argparse.Namespace) -> int:
    del args
    console = Console()
    console.print("Canonical command families:")
    console.print("- scan      preferred non-interactive reporting surface")
    console.print("- status    runtime, backend, and collector health")
    console.print("- tui       explicit Textual launcher")
    console.print()
    console.print("Available scan sections (use `kinatio scan <section>`):")
    for section in SECTIONS:
        command_name = section.lower()
        markers: list[str] = []
        category = get_section_category(section)
        if section in PRIVILEGED_SECTIONS:
            markers.append("privileged")
        if section in FOLLOWABLE_SECTIONS:
            markers.append("follow")
        marker_text = f" [{' · '.join(markers)}]" if markers else ""
        console.print(f"- {command_name}{marker_text}", markup=False)
        if category is not None:
            console.print(f"  category: {category}")
        console.print(f"  {SECTION_DESCRIPTIONS.get(section, 'No description available.')}")
        console.print(f"  preferred: kinatio scan {command_name}")
    return 0


async def _handle_tui_passthrough(args: argparse.Namespace) -> int:
    del args
    raise CLIError("the TUI is launched by the top-level entrypoint; run `kinatio tui` directly from the package entrypoint")


async def _handle_status(args: argparse.Namespace) -> int:
    context = CLIContext()
    runtime = _create_cli_runtime(context)
    await prime_runtime_store(runtime)
    context.auth_state = await runtime.auth.refresh()
    await redact_locked_privileged_state(runtime.store, context.auth_state)
    _, state = await runtime.store.snapshot()
    _persist_cache_snapshot(runtime, state)

    payload = _status_payload(state, context.auth_state)
    if args.json:
        return _emit_json_payload(payload, args.output, noun="status report")

    console, buffer = _build_console(args.output)
    auth_label, auth_style = _auth_display(context.auth_state)
    console.print(
        format_status_bar(
            "Status",
            state,
            auth_label=auth_label,
            auth_style=auth_style,
            interaction_hint="Use `kinatio scan ...` for section data and `kinatio tui` for the interactive shell.",
        )
    )
    console.print()
    console.print("Runtime context:")
    console.print(f"- distro: {state.runtime.distro_name or state.runtime.distro_id or 'n/a'}")
    console.print(f"- init system: {state.runtime.init_system or 'n/a'}")
    console.print(f"- service manager: {state.runtime.service_manager or 'n/a'}")
    console.print(f"- log backend: {state.runtime.log_backend or 'n/a'}")
    console.print(f"- package manager: {state.runtime.package_manager or 'n/a'}")
    console.print(f"- firewall backend: {state.runtime.firewall_backend or 'n/a'}")
    console.print(f"- security backend: {state.runtime.security_backend or 'n/a'}")
    console.print(f"- container runtime: {state.runtime.container_runtime or 'n/a'}")
    console.print()
    console.print("Backend availability:")
    for backend_name, availability in sorted(state.backend_status.items()):
        summary = availability.reason or "no additional details"
        status = "available" if availability.available else "unavailable"
        console.print(f"- {backend_name}: {status} · {summary}")
    console.print()
    console.print("Collector health:")
    if not state.collector_health:
        console.print("- no collector health has been recorded yet")
    for collector_name, health in sorted(state.collector_health.items()):
        last_updated = health.last_finished_at or health.last_started_at
        last_updated_text = last_updated.isoformat() if last_updated else "never"
        summary = health.error or health.availability.reason or "healthy"
        console.print(
            f"- {collector_name}: status={health.status} last={health.last_completed_status} updated={last_updated_text}"
        )
        console.print(f"  availability={health.availability.available} detail={summary}")
    return _finalize_console_output(args.output, buffer, noun="status report")


async def _handle_scan(args: argparse.Namespace) -> int:
    section_names = _resolve_section_names(args.targets)
    return await _run_scan(
        section_names,
        cached=args.cached,
        json_output=args.json,
        unlock=getattr(args, "unlock", False),
        follow=getattr(args, "follow", False),
        output_path=args.output,
    )


async def _run_scan(
    section_names: Sequence[str],
    *,
    cached: bool,
    json_output: bool,
    unlock: bool,
    follow: bool,
    output_path: Path | None,
) -> int:
    _validate_follow_usage(
        section_names,
        follow=follow,
        cached=cached,
        json_output=json_output,
        output_path=output_path,
    )

    context = CLIContext()
    runtime = _create_cli_runtime(context)
    await prime_runtime_store(runtime)
    context.auth_state = await runtime.auth.refresh()
    await redact_locked_privileged_state(runtime.store, context.auth_state)
    await _maybe_unlock_sections(context, runtime, section_names, unlock=unlock)

    if follow:
        return await _follow_logs(runtime, context.auth_state)

    if not cached:
        await _refresh_sections(runtime, section_names)

    _, state = await runtime.store.snapshot()
    _persist_cache_snapshot(runtime, state)

    if json_output:
        payload = _scan_payload(section_names, state, context.auth_state, runtime)
        noun = "scan report" if len(section_names) != 1 else f"{section_names[0].lower()} scan report"
        return _emit_json_payload(payload, output_path, noun=noun)

    console, buffer = _build_console(output_path)
    render_status_bar = len(section_names) == 1
    for index, section_name in enumerate(section_names):
        if index:
            console.print()
        _print_section(
            console,
            section_name,
            state,
            context.auth_state,
            runtime,
            render_status_bar=render_status_bar,
        )
    if not render_status_bar:
        console.print()
        auth_label, auth_style = _auth_display(context.auth_state)
        console.print(
            format_status_bar(
                f"Scan ({', '.join(section_names)})",
                state,
                auth_label=auth_label,
                auth_style=auth_style,
                interaction_hint="Batch CLI scan · use `--json` for automation or `kinatio sections` for section discovery",
                section_locked=False,
            )
        )
    return _finalize_console_output(output_path, buffer, noun="scan report")


def _build_console(output_path: Path | None) -> tuple[Console, io.StringIO | None]:
    if output_path is None:
        return Console(), None
    buffer = io.StringIO()
    return Console(file=buffer, force_terminal=False, color_system=None, width=100), buffer


def _finalize_console_output(output_path: Path | None, buffer: io.StringIO | None, *, noun: str) -> int:
    if output_path is None or buffer is None:
        return 0
    _write_output_file(output_path, buffer.getvalue())
    Console().print(f"saved {noun} to {output_path}")
    return 0


def _write_output_file(output_path: Path, content: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.chmod(0o600)
        temp_path.replace(output_path)
        output_path.chmod(0o600)
    except OSError as exc:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise CLIError(f"unable to write output file {output_path}: {exc}") from exc


def _persist_cache_snapshot(runtime: RuntimeServices, state: SystemState) -> None:
    runtime.cache.save(state_for_persistence(state))


def _emit_json_payload(payload: dict[str, Any], output_path: Path | None, *, noun: str) -> int:
    json_text = json.dumps(payload, indent=2, sort_keys=True)
    if output_path is None:
        Console().print_json(data=json_text)
        return 0
    _write_output_file(output_path, f"{json_text}\n")
    Console().print(f"saved {noun} to {output_path}")
    return 0


def _resolve_section_names(targets: Sequence[str]) -> list[str]:
    normalized = [target.strip().lower() for target in targets if target.strip()]
    if not normalized:
        raise CLIError("at least one section target is required")
    if "all" in normalized:
        if len(normalized) != 1:
            raise CLIError("`all` cannot be combined with named sections.")
        return list(SECTIONS)

    section_names: list[str] = []
    seen: set[str] = set()
    invalid_targets: list[str] = []
    for target in normalized:
        section_name = SECTION_COMMANDS.get(target)
        if section_name is None:
            invalid_targets.append(target)
            continue
        if section_name not in seen:
            seen.add(section_name)
            section_names.append(section_name)
    if invalid_targets:
        raise CLIError(f"unknown section target(s): {', '.join(invalid_targets)}")
    return section_names


def _validate_follow_usage(
    section_names: Sequence[str],
    *,
    follow: bool,
    cached: bool,
    json_output: bool,
    output_path: Path | None,
) -> None:
    if not follow:
        return
    if cached:
        raise CLIError("`--follow` cannot be combined with `--cached`.")
    if json_output:
        raise CLIError("`--follow` cannot be combined with `--json`.")
    if output_path is not None:
        raise CLIError("`--follow` cannot be combined with `--output`.")
    if list(section_names) != ["Logs"]:
        raise CLIError("`--follow` is currently only supported for the Logs section.")


async def _maybe_unlock_sections(
    context: CLIContext,
    runtime: RuntimeServices,
    section_names: Sequence[str],
    *,
    unlock: bool,
) -> None:
    if not any(section_name in PRIVILEGED_SECTIONS for section_name in section_names):
        return
    if context.auth_state.authenticated or not unlock:
        return
    if not context.auth_state.available:
        raise CLIError(context.auth_state.message)
    prompt = "sudo password: "
    if len(section_names) == 1:
        prompt = f"sudo password for {section_names[0]}: "
    context.auth_state = await _prompt_for_sudo(runtime, prompt=prompt)


async def _refresh_sections(runtime: RuntimeServices, section_names: Sequence[str]) -> None:
    if any((policy := get_section_policy(section_name)) is None or policy.subsystem is None for section_name in section_names):
        await runtime.scheduler.refresh_now()
        return

    seen_subsystems: set[str] = set()
    subsystems: list[str] = []
    for section_name in section_names:
        policy = get_section_policy(section_name)
        assert policy is not None and policy.subsystem is not None
        if policy.subsystem not in seen_subsystems:
            seen_subsystems.add(policy.subsystem)
            subsystems.append(policy.subsystem)
    await asyncio.gather(*(runtime.scheduler.refresh_now(subsystem=subsystem) for subsystem in subsystems))


async def _follow_logs(runtime: RuntimeServices, auth_state: SudoAuthState) -> int:
    if not auth_state.authenticated:
        raise CLIError("Logs follow mode requires sudo authentication. Re-run with `--unlock`.")

    await runtime.scheduler.refresh_now(subsystem="logs")
    _, state = await runtime.store.snapshot()
    console = Console()
    _print_section(console, "Logs", state, auth_state, runtime)
    console.print()
    console.print("Following Logs. Press Ctrl+C to stop.")

    logs_collector = next((collector for collector in runtime.collectors if collector.subsystem == "logs"), None)
    if logs_collector is None:
        raise CLIError("the logs collector is not available in the current runtime")

    stream = logs_collector.stream(runtime.runner, runtime.config)
    if isawaitable(stream):
        stream = await stream
    async for entry in stream:
        console.print(_format_live_log_entry(entry))
    return 0


def _print_section(
    console: Console,
    section_name: str,
    state: SystemState,
    auth_state: SudoAuthState,
    runtime: RuntimeServices,
    *,
    render_status_bar: bool = True,
) -> None:
    health = _section_health(section_name, state, runtime)
    if section_name in PRIVILEGED_SECTIONS and not auth_state.authenticated:
        console.print(format_locked_section(section_name, auth_state.status, auth_state.message))
    else:
        banner = format_section_health_banner(section_name, health)
        if banner is not None:
            console.print(banner)
        console.print(format_state_section(section_name, state))
    if render_status_bar:
        console.print()
        auth_label, auth_style = _auth_display(auth_state)
        console.print(
            format_status_bar(
                section_name,
                state,
                auth_label=auth_label,
                auth_style=auth_style,
                interaction_hint="CLI mode · use `--json` for automation or `kinatio tui` for the interactive shell",
                section_locked=section_name in PRIVILEGED_SECTIONS and not auth_state.authenticated,
            )
        )


def _format_live_log_entry(entry: LogEntry) -> str:
    timestamp = entry.timestamp.isoformat(timespec="seconds")
    priority = (entry.priority or "-").upper()
    source = entry.unit or entry.source
    return f"{timestamp}  {priority:<5}  {source}  {entry.message}"


def _scan_payload(
    section_names: Sequence[str],
    state: SystemState,
    auth_state: SudoAuthState,
    runtime: RuntimeServices,
) -> dict[str, Any]:
    return {
        "requested_sections": [section_name.lower() for section_name in section_names],
        "timestamp": state.timestamp.isoformat(),
        "auth": {
            "status": auth_state.status,
            "message": auth_state.message,
        },
        "sections": [
            _section_payload(section_name, state, auth_state, runtime)
            for section_name in section_names
        ],
    }


def _status_payload(state: SystemState, auth_state: SudoAuthState) -> dict[str, Any]:
    return {
        "timestamp": state.timestamp.isoformat(),
        "auth": {
            "status": auth_state.status,
            "message": auth_state.message,
        },
        "runtime": state.runtime.model_dump(mode="json"),
        "backends": {
            backend_name: availability.model_dump(mode="json")
            for backend_name, availability in sorted(state.backend_status.items())
        },
        "collectors": {
            collector_name: _health_payload(health)
            for collector_name, health in sorted(state.collector_health.items())
        },
    }


def _create_cli_runtime(context: CLIContext) -> RuntimeServices:
    def collection_gate(collector: Any) -> AvailabilityInfo | None:
        subsystem = getattr(collector, "subsystem", None)
        if subsystem in DEFERRED_SUBSYSTEMS and not context.auth_state.authenticated:
            return AvailabilityInfo(
                available=False,
                reason="Collection deferred until sudo authentication is unlocked.",
                dependency="sudo",
            )
        return None

    runtime = create_runtime_services(collection_gate=collection_gate)
    context.auth_state = runtime.auth.state
    return runtime


async def _prompt_for_sudo(runtime: RuntimeServices, *, prompt: str = "sudo password: ") -> SudoAuthState:
    password = getpass.getpass(prompt)
    auth_state = await runtime.auth.authenticate(password)
    if not auth_state.authenticated:
        raise CLIError(auth_state.message)
    return auth_state


def _section_health(section_name: str, state: SystemState, runtime: RuntimeServices) -> CollectorHealth | None:
    policy = get_section_policy(section_name)
    if policy is None or policy.subsystem is None:
        return None
    collector_names_by_subsystem = {
        collector.subsystem: collector.name for collector in runtime.collectors
    }
    collector_name = collector_names_by_subsystem.get(policy.subsystem, policy.subsystem)
    return state.collector_health.get(collector_name)


def _section_payload(
    section_name: str,
    state: SystemState,
    auth_state: SudoAuthState,
    runtime: RuntimeServices,
) -> dict[str, Any]:
    return {
        "section": section_name,
        "locked": section_name in PRIVILEGED_SECTIONS and not auth_state.authenticated,
        "auth": {
            "status": auth_state.status,
            "message": auth_state.message,
        },
        "health": _health_payload(_section_health(section_name, state, runtime)),
        "data": _section_data_payload(section_name, state),
    }


def _section_data_payload(section_name: str, state: SystemState) -> Any:
    return section_payload_data(section_name, state)


def _health_payload(health: CollectorHealth | None) -> dict[str, Any] | None:
    if health is None:
        return None
    return {
        "status": health.status,
        "last_completed_status": health.last_completed_status,
        "error": health.error,
        "availability": health.availability.model_dump(mode="json"),
        "last_started_at": health.last_started_at.isoformat() if health.last_started_at else None,
        "last_finished_at": health.last_finished_at.isoformat() if health.last_finished_at else None,
        "duration_ms": health.duration_ms,
    }


def _auth_display(auth_state: SudoAuthState) -> tuple[str, str]:
    if auth_state.status == "authenticated":
        return "authenticated", "bold white"
    if auth_state.status == "locked":
        return "locked", "bold red"
    return "unavailable", "grey62"
