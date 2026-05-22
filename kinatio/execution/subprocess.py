"""Safe subprocess abstractions."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass


@dataclass(slots=True)
class CommandResult:
    command: list[str]
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    missing_dependency: bool = False
    executed_with_sudo: bool = False


class SafeSubprocessRunner:
    """Runs external commands without shell interpolation."""

    _SAFE_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM", "TZ")

    def _finalize_command(self, command: list[str], *, prepend_sudo: bool) -> list[str]:
        if not command:
            raise ValueError("command must not be empty")
        if prepend_sudo and command[0] == "sudo":
            raise ValueError("command must not already include sudo when prepend_sudo=True")
        return ["sudo", "--non-interactive", *command] if prepend_sudo else command

    def _resolve_env(
        self,
        env: Mapping[str, str] | None,
        *,
        prepend_sudo: bool,
    ) -> dict[str, str] | None:
        if env is not None:
            return dict(env)
        if not prepend_sudo:
            return None
        filtered = {
            key: value
            for key, value in os.environ.items()
            if key in self._SAFE_ENV_KEYS and value
        }
        filtered.setdefault("PATH", os.defpath)
        return filtered

    async def run(
        self,
        command: list[str],
        *,
        timeout: float | None = 10.0,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        allow_missing: bool = False,
        prepend_sudo: bool = False,
    ) -> CommandResult:
        final_command = self._finalize_command(command, prepend_sudo=prepend_sudo)
        executable = final_command[0]
        if shutil.which(executable) is None:
            if allow_missing:
                return CommandResult(
                    command=final_command,
                    stdout="",
                    stderr=f"Missing dependency: {executable}",
                    returncode=127,
                    missing_dependency=True,
                    executed_with_sudo=prepend_sudo,
                )
            raise FileNotFoundError(executable)
        process = await asyncio.create_subprocess_exec(
            *final_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if input_text is not None else None,
            env=self._resolve_env(env, prepend_sudo=prepend_sudo),
        )
        try:
            stdin_bytes = input_text.encode() if input_text is not None else None
            if timeout is None:
                stdout, stderr = await process.communicate(stdin_bytes)
            else:
                stdout, stderr = await asyncio.wait_for(process.communicate(stdin_bytes), timeout=timeout)
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            return CommandResult(
                command=final_command,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                returncode=process.returncode or -9,
                timed_out=True,
                executed_with_sudo=prepend_sudo,
            )
        return CommandResult(
            command=final_command,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            returncode=process.returncode or 0,
            executed_with_sudo=prepend_sudo,
        )

    async def stream_lines(
        self,
        command: list[str],
        *,
        timeout: float | None,
        env: Mapping[str, str] | None = None,
        prepend_sudo: bool = False,
    ) -> AsyncIterator[str]:
        final_command = self._finalize_command(command, prepend_sudo=prepend_sudo)
        executable = final_command[0]
        if shutil.which(executable) is None:
            raise FileNotFoundError(executable)
        process = await asyncio.create_subprocess_exec(
            *final_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._resolve_env(env, prepend_sudo=prepend_sudo),
        )
        assert process.stdout is not None
        try:
            while True:
                line_task = process.stdout.readline()
                try:
                    line = await asyncio.wait_for(line_task, timeout=timeout)
                except TimeoutError:
                    process.kill()
                    await process.communicate()
                    break
                if not line:
                    break
                yield line.decode(errors="replace").rstrip()
        finally:
            if process.returncode is None:
                process.kill()
                await process.communicate()
