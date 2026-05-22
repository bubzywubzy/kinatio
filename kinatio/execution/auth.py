"""Interactive sudo session coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kinatio.execution.subprocess import CommandResult, SafeSubprocessRunner


@dataclass(slots=True, frozen=True)
class SudoAuthState:
    status: Literal["unavailable", "locked", "authenticated"]
    message: str
    command: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.status != "unavailable"

    @property
    def authenticated(self) -> bool:
        return self.status == "authenticated"

    @classmethod
    def unavailable(cls, message: str = "sudo is not available on this host.") -> SudoAuthState:
        return cls(status="unavailable", message=message)

    @classmethod
    def locked(cls, message: str = "sudo credentials are required.", command: list[str] | None = None) -> SudoAuthState:
        return cls(status="locked", message=message, command=command or [])

    @classmethod
    def authenticated_state(
        cls,
        message: str = "sudo unlocked for the current session.",
        command: list[str] | None = None,
    ) -> SudoAuthState:
        return cls(status="authenticated", message=message, command=command or [])


class SudoAuthCoordinator:
    """Validates and tracks the current sudo session state."""

    def __init__(self, runner: SafeSubprocessRunner) -> None:
        self.runner = runner
        self._state = SudoAuthState.locked("Checking sudo status.")

    @property
    def state(self) -> SudoAuthState:
        return self._state

    async def refresh(self) -> SudoAuthState:
        result = await self.runner.run(["sudo", "-n", "-v"], timeout=5.0, allow_missing=True)
        self._state = self._state_from_probe(result)
        return self._state

    async def authenticate(self, password: str) -> SudoAuthState:
        if not password:
            self._state = SudoAuthState.locked("Password is required to unlock sudo-protected categories.")
            return self._state
        result = await self.runner.run(
            ["sudo", "-S", "-p", "", "-v"],
            timeout=10.0,
            allow_missing=True,
            input_text=f"{password}\n",
        )
        self._state = self._state_from_auth(result)
        return self._state

    def _state_from_probe(self, result: CommandResult) -> SudoAuthState:
        if result.missing_dependency:
            return SudoAuthState.unavailable(result.stderr or "sudo is not installed.")
        if result.returncode == 0 and not result.timed_out:
            return SudoAuthState.authenticated_state(
                "sudo is already unlocked for this session.",
                command=result.command,
            )
        message = (result.stderr or result.stdout).strip() or "sudo is available but currently locked."
        return SudoAuthState.locked(message, command=result.command)

    def _state_from_auth(self, result: CommandResult) -> SudoAuthState:
        if result.missing_dependency:
            return SudoAuthState.unavailable(result.stderr or "sudo is not installed.")
        if result.returncode == 0 and not result.timed_out:
            return SudoAuthState.authenticated_state(command=result.command)
        message = (result.stderr or result.stdout).strip() or "sudo authentication failed."
        return SudoAuthState.locked(message, command=result.command)