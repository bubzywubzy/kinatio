import kinatio.__main__ as entrypoint


def test_main_runs_tui_when_no_args(monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.setattr(entrypoint, "run_tui", lambda: calls.append("tui") or 0)
    monkeypatch.setattr(entrypoint, "cli_main", lambda args: calls.append(("cli", args)) or 0)

    result = entrypoint.main([])

    assert result == 0
    assert calls == ["tui"]


def test_main_routes_cli_commands(monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.setattr(entrypoint, "run_tui", lambda: calls.append("tui") or 0)
    monkeypatch.setattr(entrypoint, "cli_main", lambda args: calls.append(("cli", args)) or 0)

    result = entrypoint.main(["scan", "system", "--cached"])

    assert result == 0
    assert calls == [("cli", ["scan", "system", "--cached"])]


def test_main_routes_tui_alias_to_tui(monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.setattr(entrypoint, "run_tui", lambda: calls.append("tui") or 0)
    monkeypatch.setattr(entrypoint, "cli_main", lambda args: calls.append(("cli", args)) or 0)

    result = entrypoint.main(["tui"])

    assert result == 0
    assert calls == ["tui"]


def test_main_routes_tui_flag_alias_to_tui(monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.setattr(entrypoint, "run_tui", lambda: calls.append("tui") or 0)
    monkeypatch.setattr(entrypoint, "cli_main", lambda args: calls.append(("cli", args)) or 0)

    result = entrypoint.main(["--tui"])

    assert result == 0
    assert calls == ["tui"]
