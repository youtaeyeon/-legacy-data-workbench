from pathlib import Path

import pytest

from hospital_marketing.ai.adapters.gemini_provider import GeminiProvider
from hospital_marketing.domain import ContentItem
from hospital_marketing.providers import ProviderRequestError, sanitize_provider_error_message
from tests.live_env import read_gemini_api_key


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.live
def test_live_gemini_connection_and_content_classification():
    api_key = read_gemini_api_key(REPOSITORY_ROOT / ".env")
    if not api_key:
        pytest.skip("GEMINI_API_KEY가 환경 변수 또는 저장소 루트 .env에 없습니다.")

    provider = GeminiProvider(api_key=api_key, model="gemini-3.8-flash")
    try:
        provider.test_connection()
        result = provider.classify_content(
            ContentItem(
                hospital_id="MOCK-LIVE-001",
                platform="YouTube",
                title="울트라클리어 소개 콘텐츠",
                url="https://example.test/mock-content",
                description="목업 제품 소개 콘텐츠입니다.",
                published_at=None,
                matched_product=None,
                relevance_status="pending",
                evidence=None,
            ),
            ("울트라클리어", "리뉴비온", "피아모"),
        )
    except ProviderRequestError as exc:
        safe_message = sanitize_provider_error_message(str(exc), api_key)
        if "HTTP 429" in safe_message:
            pytest.skip("한도 초과로 확인 보류")
        raise AssertionError(safe_message) from None
    except Exception as exc:
        safe_message = sanitize_provider_error_message(str(exc), api_key)
        raise AssertionError(safe_message or "Gemini 연결 테스트에 실패했습니다.") from None

    assert result.relevance_status in {"relevant", "irrelevant", "needs_review"}
