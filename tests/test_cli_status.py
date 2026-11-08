import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from hospital_marketing.ai import cli_status


@pytest.mark.parametrize("cli", ["claude", "codex", "gemini"])
def test_cli_status_reports_first_version_line_and_safe_command(monkeypatch, cli):
    calls = []
    monkeypatch.setattr(cli_status.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "v1.2.3\nextra details", "")

    monkeypatch.setattr(cli_status.subprocess, "run", fake_run)

    status = cli_status.check_cli_status(cli)

    assert status.installed is True
    assert status.path == f"/usr/bin/{cli}"
    assert status.version == "v1.2.3"
    assert status.error is None
    assert calls[0][0] == [f"/usr/bin/{cli}", "--version"]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["timeout"] == 10


def test_cli_status_reports_missing_executable(monkeypatch):
    monkeypatch.setattr(cli_status.shutil, "which", lambda _name: None)

    status = cli_status.check_cli_status("claude")

    assert status.installed is False
    assert status.path is None
    assert status.version is None
    assert "설치되지 않았습니다" in status.error


def test_cli_status_finds_windows_user_install_outside_path(monkeypatch, tmp_path):
    known = tmp_path / ".local" / "bin" / "claude.exe"
    known.parent.mkdir(parents=True)
    known.touch()
    monkeypatch.setattr(cli_status.shutil, "which", lambda _name: None)
    monkeypatch.setattr(cli_status, "_known_windows_paths", lambda _cli: (known,))
    monkeypatch.setattr(
        cli_status.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "2.0.0\n", ""),
    )

    status = cli_status.check_cli_status("claude")

    assert status.installed is True
    assert status.path == str(known)
    assert status.version == "2.0.0"


def test_cli_status_translates_version_timeout(monkeypatch):
    monkeypatch.setattr(cli_status.shutil, "which", lambda _name: "/usr/bin/gemini")
    monkeypatch.setattr(
        cli_status.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("gemini", 10)),
    )

    status = cli_status.check_cli_status("gemini")

    assert status.installed is True
    assert status.path == "/usr/bin/gemini"
    assert status.version is None
    assert "시간이 초과" in status.error


def test_cli_status_rejects_unknown_cli():
    with pytest.raises(ValueError, match="지원하지 않는 CLI"):
        cli_status.check_cli_status("sh")


def test_node_tool_status_checks_node_and_npm(monkeypatch):
    monkeypatch.setattr(cli_status.shutil, "which", lambda name: f"/usr/bin/{name}")

    statuses = cli_status.check_node_tool_status()

    assert statuses == {"node": "/usr/bin/node", "npm": "/usr/bin/npm"}


def test_node_tool_status_reports_missing_tools(monkeypatch):
    monkeypatch.setattr(cli_status.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)

    statuses = cli_status.check_node_tool_status()

    assert statuses == {"node": "/usr/bin/node", "npm": None}


def test_windows_cmd_version_check_uses_comspec_without_shell(monkeypatch):
    monkeypatch.setattr(cli_status, "os", SimpleNamespace(name="nt", environ={"COMSPEC": "cmd.exe"}))

    command = cli_status._version_command(r"C:\Users\Test User\AppData\Roaming\npm\codex.cmd")

    assert command[:4] == ["cmd.exe", "/d", "/s", "/c"]
    assert '"C:\\Users\\Test User\\AppData\\Roaming\\npm\\codex.cmd" --version' == command[4]
