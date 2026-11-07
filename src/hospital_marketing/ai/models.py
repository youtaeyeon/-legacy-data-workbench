from __future__ import annotations

import re


# Keep the dropdown suggestions in one place; users may still enter other IDs.
RECOMMENDED_MODELS: dict[str, tuple[str, ...]] = {
    "mock": (),
    "openai": ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra"),
    "anthropic": ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"),
    "gemini": ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-4-argon"),
    "local-cli": ("claude", "codex", "gemini"),
}

MODEL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def model_id_error(provider_id: str, model_id: str) -> str | None:
    if provider_id == "mock":
        return None
    if not model_id.strip():
        if provider_id == "local-cli":
            return "CLI를 선택해 주세요."
        return "모델 ID가 비어 있습니다. 권장 모델을 선택하거나 모델 ID를 입력해 주세요."
    if provider_id == "local-cli" and model_id.strip() not in RECOMMENDED_MODELS[provider_id]:
        return "지원하지 않는 CLI입니다. claude, codex, gemini 중에서 선택하세요."
    if not MODEL_ID_PATTERN.fullmatch(model_id.strip()):
        return "모델 ID 형식이 올바르지 않습니다. 영문·숫자와 점(.), 밑줄(_), 하이픈(-), 콜론(:)만 사용할 수 있습니다."
    return None
