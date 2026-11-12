from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess


SUPPORTED_CLIS = ("claude", "codex", "gemini")
VERSION_TIMEOUT_SECONDS = 10
_CLI_INSTALL_COMMANDS = {
    "claude": "irm https://claude.ai/install.ps1 | iex",
    "codex": "npm.cmd install -g @openai/codex",
    "gemini": "npm.cmd install -g @google/gemini-cli",
}
_CLI_LOGIN_COMMANDS = {"claude": "claude", "codex": "codex login", "gemini": "gemini"}
CLI_INSTALL_DOCS = {
    "claude": "https://code.claude.com/docs/en/setup",
    "codex": "https://developers.openai.com/codex/cli/",
    "gemini": "https://geminicli.com/docs/get-started/installation/",
}


@dataclass(frozen=True)
class CLIStatus:
    installed: bool
    path: str | None
    version: str | None
    error: str | None


def _known_windows_paths(cli: str) -> tuple[Path, ...]:
    if os.name != "nt":
        return ()
    candidates: list[Path] = []
    user_profile = os.environ.get("USERPROFILE")
    appdata = os.environ.get("APPDATA")
    suffixes = (".exe", ".cmd", "")
    if user_profile:
        candidates.extend(Path(user_profile, ".local", "bin", f"{cli}{suffix}") for suffix in suffixes)
    if appdata:
        candidates.extend(Path(appdata, "npm", f"{cli}{suffix}") for suffix in suffixes)
    return tuple(candidates)


def find_executable(cli: str) -> str | None:
    if cli not in SUPPORTED_CLIS:
        raise ValueError(f"지원하지 않는 CLI입니다: {cli}")
    executable = shutil.which(cli)
    if executable:
        return executable
    for candidate in _known_windows_paths(cli):
        if candidate.is_file():
            return str(candidate)
    return None


def _version_command(executable: str) -> list[str]:
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        command = subprocess.list2cmdline([executable, "--version"])
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command]
    return [executable, "--version"]


def check_cli_status(cli: str) -> CLIStatus:
    if cli not in SUPPORTED_CLIS:
        raise ValueError(f"지원하지 않는 CLI입니다: {cli}")
    executable = find_executable(cli)
    if not executable:
        return CLIStatus(False, None, None, f"{cli} CLI가 설치되지 않았습니다.")
    try:
        run_options = {}
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            run_options = {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": startupinfo}
        completed = subprocess.run(
            _version_command(executable),
            shell=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=VERSION_TIMEOUT_SECONDS,
            check=False,
            **run_options,
        )
    except subprocess.TimeoutExpired:
        return CLIStatus(True, executable, None, f"{cli} 버전 확인 시간이 초과되었습니다.")
    except OSError:
        return CLIStatus(True, executable, None, f"{cli} 실행 파일을 실행할 수 없습니다.")
    if completed.returncode != 0:
        return CLIStatus(True, executable, None, f"{cli} 버전 확인에 실패했습니다.")
    version = next((line.strip() for line in completed.stdout.splitlines() if line.strip()), None)
    if not version:
        return CLIStatus(True, executable, None, f"{cli} 버전 정보가 비어 있습니다.")
    return CLIStatus(True, executable, version, None)


def check_cli_auth_status(cli: str) -> tuple[bool | None, str | None]:
    """Read local CLI authentication state without starting a model request."""
    if cli not in SUPPORTED_CLIS:
        raise ValueError(f"지원하지 않는 CLI입니다: {cli}")
    if cli == "gemini":
        credentials = Path.home() / ".gemini" / "oauth_creds.json"
        authenticated = bool(os.environ.get("GEMINI_API_KEY")) or credentials.is_file()
        return authenticated, None if authenticated else "gemini CLI 로그인이 필요합니다."

    executable = find_executable(cli)
    if not executable:
        return False, f"{cli} CLI가 설치되지 않았습니다."
    command = (
        [executable, "auth", "status", "--text"]
        if cli == "claude"
        else [executable, "login", "status"]
    )
    run_options = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        run_options = {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": startupinfo}
    try:
        completed = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=VERSION_TIMEOUT_SECONDS,
            check=False,
            **run_options,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, f"{cli} 로그인 상태를 확인하지 못했습니다."
    if completed.returncode == 0:
        return True, None
    return False, f"{cli} CLI 로그인이 필요합니다."


def check_all_cli_statuses() -> dict[str, CLIStatus]:
    return {cli: check_cli_status(cli) for cli in SUPPORTED_CLIS}


def check_node_tool_status() -> dict[str, str | None]:
    return {name: shutil.which(name) for name in ("node", "npm")}


def cli_install_command(cli: str, *, node_available: bool = True) -> str:
    if cli not in _CLI_INSTALL_COMMANDS:
        raise ValueError(f"지원하지 않는 CLI입니다: {cli}")
    command = _CLI_INSTALL_COMMANDS[cli]
    if cli == "claude":
        return command
    if node_available:
        return command
    return (
        "if (-not (Get-Command node -ErrorAction SilentlyContinue) -or "
        "-not (Get-Command npm -ErrorAction SilentlyContinue)) { "
        "winget install --id OpenJS.NodeJS.LTS --exact --accept-source-agreements "
        "--accept-package-agreements; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; "
        "$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + "
        "[Environment]::GetEnvironmentVariable('Path','User') }; "
        f"{command}"
    )


def cli_login_command(cli: str) -> str:
    if cli not in _CLI_LOGIN_COMMANDS:
        raise ValueError(f"지원하지 않는 CLI입니다: {cli}")
    return _CLI_LOGIN_COMMANDS[cli]


def start_cli_terminal(cli: str, *, install: bool = False, node_available: bool = True):
    if os.name != "nt":
        raise OSError("로컬 CLI 설치 및 로그인 터미널은 Windows에서만 지원합니다.")
    command = (
        cli_install_command(cli, node_available=node_available)
        if install
        else cli_login_command(cli)
    )
    return subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-Command", command],
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
