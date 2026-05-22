import pytest

from kinatio.execution.subprocess import SafeSubprocessRunner


async def test_run_rejects_pre_sudo_prefixed_commands_when_prepend_sudo_is_requested() -> None:
    runner = SafeSubprocessRunner()

    with pytest.raises(ValueError, match="already include sudo"):
        await runner.run(["sudo", "systemctl", "restart", "sshd.service"], prepend_sudo=True)


async def test_run_filters_environment_for_sudo_prefixed_commands(monkeypatch) -> None:
    runner = SafeSubprocessRunner()
    captured: dict[str, object] = {}

    class _FakeProcess:
        returncode = 0

        async def communicate(self, input_text=None):
            del input_text
            return b"ok", b""

    async def fake_create_subprocess_exec(*command, **kwargs):
        captured["command"] = list(command)
        captured["env"] = kwargs.get("env")
        return _FakeProcess()

    monkeypatch.setattr("kinatio.execution.subprocess.shutil.which", lambda executable: f"/usr/bin/{executable}")
    monkeypatch.setattr("kinatio.execution.subprocess.asyncio.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("SECRET_TOKEN", "keep-me-out")

    result = await runner.run(["journalctl", "-n", "1"], prepend_sudo=True)

    assert result.executed_with_sudo is True
    assert captured["command"] == ["sudo", "--non-interactive", "journalctl", "-n", "1"]
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["LANG"] == "C.UTF-8"
    assert "SECRET_TOKEN" not in env