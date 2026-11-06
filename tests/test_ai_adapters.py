import json

import pytest

from hospital_marketing.ai.adapters.anthropic_provider import AnthropicProvider
from hospital_marketing.ai.adapters.gemini_provider import GeminiProvider
from hospital_marketing.ai.adapters.openai_provider import OpenAIProvider
from hospital_marketing.ai.base import RelevanceResult
from hospital_marketing.ai.registry import ProviderRegistry
from hospital_marketing.domain import ContentItem
from hospital_marketing.providers import ProviderConfigurationError, ProviderRequestError


ANSWER = {"relevance_status": "relevant", "matched_product": "울트라클리어", "evidence": "제목에서 확인"}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def post(self, url, *, headers, json):
        self.calls.append((url, headers, json))
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


def _item():
    return ContentItem("MOCK-001", "YouTube", "울트라클리어 소개", "https://example.test/video", "목업", None, None, "pending", None)


def _fake_payload(provider_id, content):
    encoded = json.dumps(content, ensure_ascii=False)
    if provider_id == "openai":
        return {"choices": [{"message": {"content": encoded}}]}
    if provider_id == "anthropic":
        return {"content": [{"type": "text", "text": encoded}]}
    return {"candidates": [{"content": {"parts": [{"text": encoded}]}}]}


@pytest.mark.parametrize(
    "provider_id,provider_type,endpoint,key_header",
    [
        ("openai", OpenAIProvider, "api.openai.com/v1/chat/completions", "Authorization"),
        ("anthropic", AnthropicProvider, "api.anthropic.com/v1/messages", "x-api-key"),
        ("gemini", GeminiProvider, "generativelanguage.googleapis.com", "x-goog-api-key"),
    ],
)
def test_provider_adapters_use_injected_client_and_parse_result(provider_id, provider_type, endpoint, key_header):
    client = FakeClient(_fake_payload(provider_id, ANSWER))
    provider = provider_type(api_key="secret-test-key", model="test-model", http_client=client)

    result = provider.classify_content(_item(), ("울트라클리어", "리뉴비온", "피아모"))

    assert result == RelevanceResult("relevant", "울트라클리어", "제목에서 확인")
    assert endpoint in client.calls[0][0]
    assert client.calls[0][1][key_header]
    assert client.calls[0][2]["model"] == "test-model" if provider_id != "gemini" else client.calls[0][2]["generationConfig"]["responseMimeType"] == "application/json"
    assert "secret-test-key" not in client.calls[0][0]


def test_provider_requires_key_and_model_before_network_call():
    client = FakeClient(_fake_payload("openai", ANSWER))

    with pytest.raises(ProviderConfigurationError):
        OpenAIProvider(api_key="", model="test-model", http_client=client)
    with pytest.raises(ProviderConfigurationError):
        OpenAIProvider(api_key="secret", model="", http_client=client)
    assert client.calls == []


def test_untrusted_provider_product_is_sent_to_review_not_included():
    response = {"relevance_status": "relevant", "matched_product": "다른 제품", "evidence": "목업"}
    client = FakeClient(_fake_payload("openai", response))

    result = OpenAIProvider(api_key="secret", model="model", http_client=client).classify_content(_item(), ("울트라클리어",))

    assert result.relevance_status == "needs_review"
    assert result.matched_product is None


def test_provider_request_error_does_not_expose_secret_or_provider_exception():
    client = FakeClient({}, error=RuntimeError("secret-test-key in error"))
    provider = OpenAIProvider(api_key="secret-test-key", model="model", http_client=client)

    with pytest.raises(ProviderRequestError) as exc:
        provider.classify_content(_item(), ("울트라클리어",))

    assert "secret-test-key" not in str(exc.value)
    assert "in error" not in str(exc.value)


def test_registry_exposes_all_selected_providers_and_accepts_injected_client():
    registry = ProviderRegistry()
    assert set(registry.available()) == {"mock", "openai", "anthropic", "gemini"}
    provider = registry.create("openai", api_key="secret", model="model", http_client=FakeClient(_fake_payload("openai", ANSWER)))
    assert isinstance(provider, OpenAIProvider)


@pytest.mark.parametrize(
    "provider_type,payload",
    [
        (OpenAIProvider, {"choices": [{"message": {"content": "**정리 결과**"}}]}),
        (AnthropicProvider, {"content": [{"type": "text", "text": "**정리 결과**"}]}),
        (GeminiProvider, {"candidates": [{"content": {"parts": [{"text": "**정리 결과**"}]}}]}),
    ],
)
def test_remote_providers_turn_extracted_source_text_into_markdown(provider_type, payload):
    client = FakeClient(payload)
    provider = provider_type(api_key="secret-test-key", model="test-model", http_client=client)

    markdown = provider.convert_document_to_markdown("report.docx", "병원 정보와 표 데이터")

    assert markdown == "**정리 결과**"
    request = json.dumps(client.calls[0][2], ensure_ascii=False)
    assert "report.docx" in request
    assert "병원 정보와 표 데이터" in request
    assert "새로운 사실을 만들지" in request
    assert "secret-test-key" not in request
