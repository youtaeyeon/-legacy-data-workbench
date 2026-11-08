import pytest

from hospital_marketing.ai.cli_status import check_all_cli_statuses, check_node_tool_status
from hospital_marketing.ai.registry import ProviderRegistry


@pytest.mark.live
def test_live_cli_install_status():
    statuses = check_all_cli_statuses()
    for cli, status in statuses.items():
        print(f"{cli}: installed={status.installed}, path={status.path}, version={status.version}, error={status.error}")
    print(f"Node.js/npm: {check_node_tool_status()}")


@pytest.mark.live
def test_live_local_cli_connection():
    import shutil

    installed = [cli for cli in ("claude", "codex", "gemini") if shutil.which(cli)]
    if not installed:
        pytest.skip("claude/codex/gemini CLI 중 설치된 실행 파일이 없습니다.")
    provider = ProviderRegistry().create("local-cli", cli=installed[0])
    getattr(provider, "test_connection")()
