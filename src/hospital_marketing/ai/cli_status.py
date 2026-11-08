from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess


SUPPORTED_CLIS = ("claude", "codex", "gemini")
VERSION_TIMEOUT_SECONDS = 10
CLI_INSTALL_DOCS = {
    "claude": "https://code.claude.com/docs/en/quickstart",
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
        completed = subprocess.run(
            _version_command(executable),
            shell=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=VERSION_TIMEOUT_SECONDS,
            check=False,
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


def check_all_cli_statuses() -> dict[str, CLIStatus]:
    return {cli: check_cli_status(cli) for cli in SUPPORTED_CLIS}


def check_node_tool_status() -> dict[str, str | None]:
    return {name: shutil.which(name) for name in ("node", "npm")}
