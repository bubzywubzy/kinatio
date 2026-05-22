from kinatio.execution.auth import SudoAuthCoordinator
from kinatio.execution.subprocess import CommandResult


class StubRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self.results = results
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    async def run(self, command: list[str], **kwargs: object) -> CommandResult:
        self.calls.append((command, kwargs))
        return self.results.pop(0)


async def test_refresh_reports_locked_when_password_is_required() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["sudo", "-n", "-v"],
                stdout="",
                stderr="sudo: a password is required",
                returncode=1,
            )
        ]
    )
    auth = SudoAuthCoordinator(runner)  # type: ignore[arg-type]

    state = await auth.refresh()

    assert state.status == "locked"
    assert "password" in state.message


async def test_authenticate_uses_stdin_and_unlocks_session() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["sudo", "-S", "-p", "", "-v"],
                stdout="",
                stderr="",
                returncode=0,
            )
        ]
    )
    auth = SudoAuthCoordinator(runner)  # type: ignore[arg-type]

    state = await auth.authenticate("hunter2")

    assert state.status == "authenticated"
    command, kwargs = runner.calls[0]
    assert command == ["sudo", "-S", "-p", "", "-v"]
    assert kwargs["input_text"] == "hunter2\n"


async def test_refresh_reports_unavailable_when_sudo_missing() -> None:
    runner = StubRunner(
        [
            CommandResult(
                command=["sudo", "-n", "-v"],
                stdout="",
                stderr="Missing dependency: sudo",
                returncode=127,
                missing_dependency=True,
            )
        ]
    )
    auth = SudoAuthCoordinator(runner)  # type: ignore[arg-type]

    state = await auth.refresh()

    assert state.status == "unavailable"