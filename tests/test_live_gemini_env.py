from pathlib import Path

from tests.live_env import read_gemini_api_key


def test_reads_key_from_env_file_and_strips_quotes_comments_and_whitespace(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\nOTHER=value\nGEMINI_API_KEY = \" test-key \" # trailing comment\n",
        encoding="utf-8",
    )

    assert read_gemini_api_key(env_file, environ={}) == "test-key"


def test_environment_variable_takes_precedence_over_env_file(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=file-key\n", encoding="utf-8")

    assert read_gemini_api_key(env_file, environ={"GEMINI_API_KEY": " process-key "}) == "process-key"


def test_returns_empty_when_env_file_does_not_exist(tmp_path: Path):
    assert read_gemini_api_key(tmp_path / "missing.env", environ={}) == ""
