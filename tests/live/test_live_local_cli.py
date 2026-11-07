import shutil

import pytest

from hospital_marketing.ai.registry import ProviderRegistry


@pytest.mark.live
def test_live_local_cli_connection():
    registry = ProviderRegistry()
    installed = [cli for cli in ("claude", "codex", "gemini") if shutil.which(cli)]
    if not installed:
        pytest.skip("claude/codex/gemini CLI 중 설치된 실행 파일이 없습니다.")
    provider = registry.create("local-cli", cli=installed[0])
    getattr(provider, "test_connection")()
