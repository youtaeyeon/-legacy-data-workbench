from pathlib import Path
import time

import httpx
import pytest

from tests.live_env import read_gemini_api_key


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODELS = ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-4-argon")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _error_status(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    return str(error.get("status", "")) if isinstance(error, dict) else ""


def _print_result(*, model: str, json_mode: str, status: str, seconds: float, error_status: str) -> None:
    print(
        f"GEMINI_DIAG model={model} json={json_mode} status={status} "
        f"secs={seconds:.3f} error_status={error_status or '-'}"
    )


@pytest.mark.live
def test_live_gemini_model_and_request_diagnostics():
    api_key = read_gemini_api_key(REPOSITORY_ROOT / ".env")
    if not api_key:
        pytest.skip("GEMINI_API_KEY가 환경 변수 또는 저장소 루트 .env에 없습니다.")

    with httpx.Client(timeout=20.0) as client:
        started = time.monotonic()
        try:
            response = client.get(
                f"{BASE_URL}/models",
                params={"pageSize": 100},
                headers={"x-goog-api-key": api_key},
            )
            elapsed = time.monotonic() - started
            print(f"GEMINI_DIAG models status={response.status_code} secs={elapsed:.3f}")
        except httpx.TimeoutException:
            pytest.fail("Gemini 모델 목록 요청이 시간 초과됐습니다.")

        if response.status_code in {401, 403}:
            pytest.fail(f"Gemini 모델 목록 조회가 인증 오류로 실패했습니다 (HTTP {response.status_code}).")
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        available = {
            item.get("name", "").removeprefix("models/")
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }
        missing = set(MODELS) - available
        print(f"GEMINI_DIAG models missing={','.join(sorted(missing)) or '-'}")

        for model in MODELS:
            for use_json in (True, False):
                generation_config = {"responseMimeType": "application/json"} if use_json else {}
                body = {
                    "contents": [{"parts": [{"text": "Reply with the single word OK."}]}],
                    "generationConfig": generation_config,
                }
                started = time.monotonic()
                try:
                    result = client.post(
                        f"{BASE_URL}/models/{model}:generateContent",
                        headers={"x-goog-api-key": api_key},
                        json=body,
                    )
                    status = str(result.status_code)
                    provider_status = _error_status(result) if result.is_error else ""
                except httpx.TimeoutException:
                    status, provider_status = "timeout", ""
                except httpx.HTTPError as exc:
                    status, provider_status = type(exc).__name__, ""
                _print_result(
                    model=model,
                    json_mode="yes" if use_json else "no",
                    status=status,
                    seconds=time.monotonic() - started,
                    error_status=provider_status,
                )
