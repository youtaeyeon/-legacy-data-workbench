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


@pytest.mark.live
def test_live_claude_finds_channels_for_public_hospital():
    import shutil

    from hospital_marketing.channel_discovery import find_hospital_channels
    from hospital_marketing.domain import Hospital
    from hospital_marketing.providers import ProviderRequestError

    if not shutil.which("claude"):
        pytest.skip("claude CLI가 설치되지 않았습니다.")
    try:
        candidates = find_hospital_channels(
            ProviderRegistry().create("local-cli", cli="claude"),
            Hospital("LIVE-PUBLIC-001", "서울대학교병원", "서울"),
        )
    except ProviderRequestError as exc:
        if "로그인" in str(exc) or "사용량 한도" in str(exc):
            pytest.skip(str(exc))
        raise
    for candidate in candidates:
        assert candidate.url.startswith(("http://", "https://"))
