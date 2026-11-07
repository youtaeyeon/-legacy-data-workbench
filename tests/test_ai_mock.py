import socket
from datetime import date

import pytest

from hospital_marketing.ai.base import RelevanceResult
from hospital_marketing.ai.mock import MockProvider
from hospital_marketing.ai.registry import ProviderRegistry
from hospital_marketing.domain import ContentItem, Hospital


PRODUCTS = ("울트라클리어", "리뉴비온", "피아모")


def _content(title, description="", matched_product=None):
    return ContentItem(
        "MOCK-001", "YouTube", title, "https://example.test/content", description,
        date(2026, 4, 1), matched_product, "pending", None,
    )


def test_mock_provider_classifies_all_three_products_with_evidence():
    provider = MockProvider()

    for product in PRODUCTS:
        result = provider.classify_content(_content(f"{product} 사용 안내"), PRODUCTS)
        assert result.relevance_status == "relevant"
        assert result.matched_product == product
        assert product in result.evidence


def test_mock_provider_finds_product_mentioned_in_description():
    result = MockProvider().classify_content(_content("병원 소식", "오늘은 리뉴비온 사용법을 소개합니다."), PRODUCTS)

    assert result.relevance_status == "relevant"
    assert result.matched_product == "리뉴비온"
    assert "설명" in result.evidence


def test_mock_provider_excludes_unrelated_content():
    result = MockProvider().classify_content(_content("병원 일상 브이로그", "장비와 무관한 목업 콘텐츠"), PRODUCTS)

    assert result == RelevanceResult("irrelevant", None, "제품명이 확인되지 않아 관련 콘텐츠에서 제외")


def test_mock_provider_prefers_longer_matching_product():
    result = MockProvider().classify_content(
        _content("울트라클리어 엘리트 시술 후기"),
        ("울트라클리어", "울트라클리어 엘리트"),
    )

    assert result.matched_product == "울트라클리어 엘리트"


def test_mock_provider_does_not_match_disabled_products():
    result = MockProvider().classify_content(
        _content("울트라클리어 엘리트 시술 후기"),
        ("리뉴비온",),
    )

    assert result.relevance_status == "irrelevant"


def test_mock_provider_does_not_use_network(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("mock mode must not access the network")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    result = MockProvider().classify_content(_content("울트라클리어 소개"), PRODUCTS)

    assert result.relevance_status == "relevant"


def test_mock_provider_summarizes_hospital_without_api_key():
    hospital = Hospital("MOCK-001", "목업 병원 001", "가상권역 A", date(2026, 1, 10))

    summary = MockProvider().summarize_hospital(hospital)

    assert "목업 병원 001" in summary
    assert "가상권역 A" in summary


def test_mock_provider_creates_faithful_markdown_without_network(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("mock document conversion must not access the network")

    monkeypatch.setattr(socket, "create_connection", fail_network)

    markdown = MockProvider().convert_document_to_markdown("notes.txt", "병원 사실 한 줄")

    assert markdown.startswith("# notes.txt")
    assert "병원 사실 한 줄" in markdown
    assert "새로운 정보" not in markdown


def test_registry_creates_mock_provider_and_rejects_unknown_provider():
    registry = ProviderRegistry()

    assert "mock" in registry.available()
    assert isinstance(registry.create("mock"), MockProvider)
    with pytest.raises(ValueError, match="지원하지 않는 AI 제공자"):
        registry.create("unknown")
