import json
import subprocess

from hospital_marketing.ai.adapters.local_cli_provider import LocalCLIProvider
from hospital_marketing.domain import Hospital


def test_claude_channel_discovery_enables_only_web_search_tool(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, json.dumps({"result": '{"channels": []}'}), "")

    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.shutil.which", lambda _name: "/bin/claude")
    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.subprocess.run", fake_run)
    result = LocalCLIProvider("claude", temp_dir=tmp_path).discover_channels(
        Hospital("MOCK-001", "목업 병원", "가상권역")
    )

    assert result == '{"channels": []}'
    args = calls[0][0]
    assert "--allowedTools" in args and args[args.index("--allowedTools") + 1] == "WebSearch"
    assert "--tools" in args and args[args.index("--tools") + 1] == "WebSearch"
    assert "WebFetch" in args
    assert calls[0][1]["shell"] is False
    assert "MOCK-001" in args[2]
