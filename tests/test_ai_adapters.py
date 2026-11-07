import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
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


class SequenceHttpClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, headers, json):
        self.calls.append((url, headers, json))
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _http_response(status_code, *, payload=None, headers=None, content=None):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    if content is not None:
        return httpx.Response(status_code, headers=headers, content=content, request=request)
    return httpx.Response(status_code, headers=headers, json=payload, request=request)


def _success_response():
    return _http_response(200, payload=_fake_payload("openai", {"ok": True}))


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


def test_server_errors_retry_with_exponential_backoff_and_report_progress():
    client = SequenceHttpClient(
        [
            _http_response(503, payload={"error": {"status": "UNAVAILABLE", "message": "overloaded"}}),
            _http_response(503, payload={"error": {"status": "UNAVAILABLE", "message": "overloaded"}}),
            _success_response(),
        ]
    )
    delays = []
    retries = []
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=delays.append,
        jitter_fn=lambda _maximum: 0,
        on_retry=lambda *args: retries.append(args),
    )

    provider.test_connection()

    assert len(client.calls) == 3
    assert delays == [1.0, 2.0]
    assert retries == [(1, 3, 1.0), (2, 3, 2.0)]


@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
def test_exhausted_server_retries_include_provider_reason_and_model_advice(status_code):
    client = SequenceHttpClient(
        [
            _http_response(
                status_code,
                payload={
                    "error": {
                        "status": "UNAVAILABLE",
                        "message": (
                            "The model is overloaded; secret-test-key must be redacted. "
                            'Return only the JSON object {"ok": true}. Authorization: Bearer secret-test-key'
                        ),
                        "headers": {"Authorization": "Bearer secret-test-key"},
                    }
                },
            )
            for _ in range(4)
        ]
    )
    delays = []
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=delays.append,
        jitter_fn=lambda _maximum: 0,
    )

    with pytest.raises(ProviderRequestError) as exc:
        provider.test_connection()

    message = str(exc.value)
    assert len(client.calls) == 4
    assert delays == [1.0, 2.0, 4.0]
    assert f"HTTP {status_code}" in message
    assert "UNAVAILABLE" in message and "The model is overloaded" in message
    assert "3번" in message and "다른 모델" in message
    assert "gpt-6-luna" in message
    assert "secret-test-key" not in message and "Bearer" not in message
    assert "Authorization" not in message
    assert 'Return only the JSON object {"ok": true}.' not in message


@pytest.mark.parametrize(
    "prompt_excerpt",
    ["Return only the JSON", "eturn only the J", "ETURN   ONLY THE J"],
)
def test_provider_error_redacts_a_partial_prompt_excerpt(prompt_excerpt):
    client = SequenceHttpClient(
        [
            _http_response(
                503,
                payload={"error": {"status": "UNAVAILABLE", "message": f"overloaded; {prompt_excerpt}"}},
            )
            for _ in range(4)
        ]
    )
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=lambda _delay: None,
        jitter_fn=lambda _maximum: 0,
    )

    with pytest.raises(ProviderRequestError) as exc:
        provider.test_connection()

    assert "UNAVAILABLE" in str(exc.value)
    normalized_error = " ".join(str(exc.value).split()).casefold()
    normalized_excerpt = " ".join(prompt_excerpt.split()).casefold()
    assert normalized_excerpt not in normalized_error


def test_retry_after_header_is_honored_and_capped():
    client = SequenceHttpClient(
        [
            _http_response(429, headers={"Retry-After": "2"}, payload={"error": {"message": "busy"}}),
            _success_response(),
        ]
    )
    delays = []
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=delays.append,
        jitter_fn=lambda _maximum: 0,
    )

    provider.test_connection()

    assert len(client.calls) == 2
    assert delays == [2.0]


def test_retry_after_delay_is_capped_at_ten_seconds():
    client = SequenceHttpClient(
        [
            _http_response(429, headers={"Retry-After": "100"}, payload={"error": {"message": "busy"}}),
            _success_response(),
        ]
    )
    delays = []
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=delays.append,
        jitter_fn=lambda _maximum: 0,
    )

    provider.test_connection()

    assert delays == [10.0]


def test_http_date_retry_after_is_parsed_and_capped():
    retry_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    retry_after = format_datetime(retry_at, usegmt=True)
    client = SequenceHttpClient(
        [
            _http_response(429, headers={"Retry-After": retry_after}, payload={"error": {"message": "busy"}}),
            _success_response(),
        ]
    )
    delays = []
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=delays.append,
        jitter_fn=lambda _maximum: 0,
    )

    provider.test_connection()

    assert len(client.calls) == 2
    assert delays == [10.0]


@pytest.mark.parametrize("retry_after", [None, "NaN", "inf", "-1", "invalid"])
def test_rate_limit_without_valid_retry_after_is_not_retried(retry_after):
    headers = {"Retry-After": retry_after} if retry_after is not None else None
    client = SequenceHttpClient(
        [_http_response(429, headers=headers, payload={"error": {"message": "busy"}})]
    )
    delays = []
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=delays.append,
        jitter_fn=lambda _maximum: 0,
    )

    with pytest.raises(ProviderRequestError) as exc:
        provider.test_connection()

    assert len(client.calls) == 1
    assert delays == []
    assert "HTTP 429" in str(exc.value)
    assert "Retry-After 정보가 없어" in str(exc.value)


def test_rate_limit_retries_at_most_three_times():
    client = SequenceHttpClient(
        [
            _http_response(429, headers={"Retry-After": "2"}, payload={"error": {"message": "busy"}})
            for _ in range(4)
        ]
    )
    delays = []
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=delays.append,
        jitter_fn=lambda _maximum: 0,
    )

    with pytest.raises(ProviderRequestError) as exc:
        provider.test_connection()

    assert len(client.calls) == 4
    assert delays == [2.0, 2.0, 2.0]
    assert "3번" in str(exc.value)


@pytest.mark.parametrize("status_code", [401, 403, 404])
def test_authentication_and_model_errors_are_not_retried(status_code):
    client = SequenceHttpClient(
        [_http_response(status_code, payload={"error": {"message": "invalid settings"}})]
    )
    delays = []
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=delays.append,
        jitter_fn=lambda _maximum: 0,
    )

    with pytest.raises(ProviderRequestError):
        provider.test_connection()

    assert len(client.calls) == 1
    assert delays == []


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("fake timeout"),
        httpx.ConnectError("fake connection error", request=httpx.Request("POST", "https://example.test")),
    ],
)
def test_timeout_and_connection_errors_retry_once(error):
    client = SequenceHttpClient([error, _success_response()])
    delays = []
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=delays.append,
        jitter_fn=lambda _maximum: 0,
    )

    provider.test_connection()

    assert len(client.calls) == 2
    assert delays == [1.0]


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("fake timeout"),
        httpx.ConnectError("fake connection error", request=httpx.Request("POST", "https://example.test")),
    ],
)
def test_timeout_and_connection_errors_stop_after_one_retry(error):
    client = SequenceHttpClient([error, error])
    delays = []
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=delays.append,
        jitter_fn=lambda _maximum: 0,
    )

    with pytest.raises(ProviderRequestError):
        provider.test_connection()

    assert len(client.calls) == 2
    assert delays == [1.0]


def test_exponential_backoff_applies_injected_jitter():
    client = SequenceHttpClient(
        [
            _http_response(503, payload={"error": {"message": "busy"}}),
            _success_response(),
        ]
    )
    delays = []
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=delays.append,
        jitter_fn=lambda maximum: maximum,
    )

    provider.test_connection()

    assert delays == [1.1]


@pytest.mark.parametrize("content", [b"not-json", b""])
def test_invalid_or_empty_provider_error_body_is_handled_safely(content):
    client = SequenceHttpClient([_http_response(503, content=content) for _ in range(4)])
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=lambda _delay: None,
        jitter_fn=lambda _maximum: 0,
    )

    with pytest.raises(ProviderRequestError) as exc:
        provider.test_connection()

    assert len(client.calls) == 4
    assert "HTTP 503" in str(exc.value)
    assert "not-json" not in str(exc.value)
    assert "secret-test-key" not in str(exc.value)


def test_provider_error_detail_is_limited_to_two_hundred_characters():
    client = SequenceHttpClient(
        [
            _http_response(
                503,
                payload={"error": {"status": "UNAVAILABLE", "message": "x" * 500}},
            )
            for _ in range(4)
        ]
    )
    provider = OpenAIProvider(
        api_key="secret-test-key",
        model="test-model",
        http_client=client,
        sleep_fn=lambda _delay: None,
        jitter_fn=lambda _maximum: 0,
    )

    with pytest.raises(ProviderRequestError) as exc:
        provider.test_connection()

    detail = str(exc.value).split("HTTP 503 · ", 1)[1].split(").", 1)[0]
    assert len(detail) == 200


@pytest.mark.parametrize(
    "prefix",
    ["Incorrect API key provided: ", "Provider echoed token "],
)
@pytest.mark.parametrize("star_count", [3, 9])
@pytest.mark.parametrize("split_suffix", [False, True])
def test_provider_error_detail_redacts_masked_key_tokens(prefix, star_count, split_suffix):
    masked_token = "sk-proj-" + "*" * star_count + (" abcd" if split_suffix else "abcd")
    fake_api_key = "fake-test-key"
    client = SequenceHttpClient(
        [
            _http_response(
                401,
                payload={"error": {"message": f"{prefix}{masked_token}"}},
            )
        ]
    )
    provider = OpenAIProvider(
        api_key=fake_api_key,
        model="test-model",
        http_client=client,
    )

    with pytest.raises(ProviderRequestError) as exc:
        provider.test_connection()

    error = str(exc.value)
    assert len(client.calls) == 1
    assert "[REDACTED]" in error
    assert "sk-proj-" not in error
    assert "abcd" not in error


def test_registry_exposes_all_selected_providers_and_accepts_injected_client():
    registry = ProviderRegistry()
    assert set(registry.available()) == {"mock", "openai", "anthropic", "gemini", "local-cli"}
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
