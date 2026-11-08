import json
import os
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

from hospital_marketing.ai.adapters.local_cli_provider import LocalCLIProvider
from hospital_marketing.domain import ContentItem
from hospital_marketing.ai.models import RECOMMENDED_MODELS, model_id_error
from hospital_marketing.ai.registry import ProviderRegistry
from hospital_marketing.providers import ProviderConfigurationError, ProviderRequestError


def _completed(stdout, returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_local_cli_is_registered_and_has_only_recommended_commands():
    registry = ProviderRegistry()
    assert "local-cli" in registry.available()
    assert RECOMMENDED_MODELS["local-cli"] == ("claude", "codex", "gemini")
    assert model_id_error("local-cli", "gemini") is None
    assert model_id_error("local-cli", "bash")
    with pytest.raises(ProviderConfigurationError):
        registry.create("local-cli", cli="bash")


def test_claude_invocation_disables_tools_and_extracts_json_result(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return _completed(json.dumps({"result": "hello", "is_error": False}))

    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.shutil.which", lambda name: "/bin/claude")
    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.subprocess.run", fake_run)
    provider = LocalCLIProvider("claude", timeout=19, temp_dir=tmp_path)

    assert provider._complete("prompt") == "hello"
    args, options = calls[0]
    assert args == ["/bin/claude", "-p", "prompt", "--output-format", "json", "--tools", ""]
    assert options["shell"] is False
    assert options["encoding"] == "utf-8"
    assert options["timeout"] == 19
    assert Path(options["cwd"]).is_relative_to(tmp_path)


def test_codex_and_gemini_receive_prompt_as_single_argument(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _completed("plain output")

    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.subprocess.run", fake_run)
    for cli, prefix in (("codex", ["/bin/codex", "exec"]), ("gemini", ["/bin/gemini", "-p"])):
        assert LocalCLIProvider(cli, temp_dir=tmp_path)._complete("hello; do not split") == "plain output"
        assert calls[-1] == prefix + ["hello; do not split"]


def test_long_prompt_is_passed_through_utf8_stdin(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return _completed("ok")

    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.shutil.which", lambda _name: "/bin/gemini")
    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.subprocess.run", fake_run)
    prompt = "x" * 20_000
    LocalCLIProvider("gemini", temp_dir=tmp_path)._complete(prompt)

    args, options = calls[0]
    assert "x" * 100 not in " ".join(args)
    assert options["input"] == prompt


@pytest.mark.parametrize(
    ("cli", "expected_command"),
    [
        ("claude", ["cmd.exe", "/d", "/s", "/c", 'C:\\tools\\claude.cmd -p --output-format json --tools ""']),
        ("codex", ["cmd.exe", "/d", "/s", "/c", "C:\\tools\\codex.cmd exec -"]),
        ("gemini", ["cmd.exe", "/d", "/s", "/c", "C:\\tools\\gemini.cmd -p"]),
    ],
)
def test_windows_cmd_receives_untrusted_prompt_only_via_stdin(
    tmp_path, monkeypatch, cli, expected_command
):
    calls = []
    prompt = '{"title": "a & b | %PATH% > x ^ \\\"quoted\\\""}'

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return _completed(json.dumps({"result": "ok"}) if cli == "claude" else "ok")

    monkeypatch.setattr(
        "hospital_marketing.ai.adapters.local_cli_provider.os",
        SimpleNamespace(name="nt", environ={**os.environ, "COMSPEC": "cmd.exe"}),
    )
    monkeypatch.setattr(
        "hospital_marketing.ai.adapters.local_cli_provider.shutil.which",
        lambda _name: f"C:\\tools\\{cli}.cmd",
    )
    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.subprocess.run", fake_run)

    assert LocalCLIProvider(cli, temp_dir=tmp_path)._complete(prompt) == "ok"

    command, options = calls[0]
    assert command == expected_command
    assert options["input"] == prompt
    assert prompt not in " ".join(command)


def test_missing_cli_timeout_nonzero_and_invalid_claude_json_are_translated(tmp_path, monkeypatch):
    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.shutil.which", lambda _name: None)
    monkeypatch.setattr("hospital_marketing.ai.cli_status._known_windows_paths", lambda _cli: ())
    with pytest.raises(ProviderRequestError, match="설치"):
        LocalCLIProvider("gemini", temp_dir=tmp_path)._complete("prompt")

    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.subprocess.run", lambda *_a, **_k: (_ for _ in ()).throw(subprocess.TimeoutExpired("gemini", 120)))
    with pytest.raises(ProviderRequestError, match="시간"):
        LocalCLIProvider("gemini", temp_dir=tmp_path)._complete("prompt")

    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.subprocess.run", lambda *_a, **_k: _completed("", 1, "not logged in"))
    with pytest.raises(ProviderRequestError, match="로그인"):
        LocalCLIProvider("gemini", temp_dir=tmp_path)._complete("prompt")

    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.subprocess.run", lambda *_a, **_k: _completed("", 1, "quota exceeded"))
    with pytest.raises(ProviderRequestError, match="사용량 한도"):
        LocalCLIProvider("gemini", temp_dir=tmp_path)._complete("prompt")

    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.subprocess.run", lambda *_a, **_k: _completed("not-json"))
    with pytest.raises(ProviderRequestError, match="응답"):
        LocalCLIProvider("claude", temp_dir=tmp_path)._complete("prompt")


def test_local_cli_does_not_pass_app_api_key_environment_variables(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(kwargs["env"])
        return _completed("ok")

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.shutil.which", lambda _name: "/bin/gemini")
    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.subprocess.run", fake_run)

    LocalCLIProvider("gemini", temp_dir=tmp_path)._complete("prompt")

    assert all(name not in calls[0] for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"))


def test_local_cli_observes_pre_cancelled_connection_event(tmp_path, monkeypatch):
    from threading import Event

    event = Event()
    event.set()
    monkeypatch.setattr(
        "hospital_marketing.ai.adapters.local_cli_provider.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("cancelled CLI must not start"),
    )

    with pytest.raises(ProviderRequestError, match="취소"):
        LocalCLIProvider("claude", cancel_event=event, temp_dir=tmp_path).test_connection()


def test_local_cli_connection_and_provider_operations_reuse_prompt_contract(tmp_path, monkeypatch):
    prompts = []

    def fake_run(args, **_kwargs):
        prompt = args[2] if args[1] in {"-p", "exec"} else args[1]
        prompts.append(prompt)
        if '"ok"' in prompt:
            return _completed(json.dumps({"result": '{"ok": true}'}))
        return _completed(json.dumps({"result": json.dumps({"relevance_status": "relevant", "matched_product": "제품", "evidence": "근거"}, ensure_ascii=False)}))

    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr("hospital_marketing.ai.adapters.local_cli_provider.subprocess.run", fake_run)
    provider = LocalCLIProvider("claude", temp_dir=tmp_path)
    provider.test_connection()
    result = provider.classify_content(
        ContentItem("MOCK-001", "YouTube", "제목", "https://example.test/video", "설명", None, None, "pending", None),
        ("제품",),
    )
    assert result.relevance_status == "relevant"
    assert result.matched_product == "제품"
    assert len(prompts) == 2
