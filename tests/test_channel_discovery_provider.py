import json
import subprocess

from hospital_marketing.ai.adapters.local_cli_provider import LocalCLIProvider
from hospital_marketing.domain import Hospital
from hospital_marketing.channel_discovery import parse_discovery_response


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


def test_parse_discovery_response_keeps_valid_channels_and_posts_independently():
    payload = json.dumps({
        "channels": [
            {"platform": "인스타그램", "channel_name": "목업 계정", "url": "https://instagram.com/mock",
             "evidence": "병원 공식 링크", "confidence": 0.9},
            {"platform": "유튜브", "channel_name": "잘못된 링크", "url": "https://example.test/no",
             "evidence": "잘못된 도메인", "confidence": 0.8},
        ],
        "posts": [
            {"platform": "인스타그램", "title": "목업 게시물", "url": "https://instagram.com/p/1",
             "published_at": "2026-11-01", "summary": "첫 문장. 둘째 문장.", "channel_url": "https://instagram.com/mock"},
            {"platform": "유튜브", "title": "잘못된 게시물", "url": "javascript:alert(1)",
             "published_at": "2026-11-02", "summary": "폐기", "channel_url": "https://youtube.com/@mock"},
        ],
    })

    channels, posts, discarded = parse_discovery_response(payload)

    assert [item.url for item in channels] == ["https://instagram.com/mock"]
    assert [item.url for item in posts] == ["https://instagram.com/p/1"]
    assert discarded == 2
