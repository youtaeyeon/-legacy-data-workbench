from collections.abc import Sequence

from ..domain import ContentItem, Hospital
from .base import RelevanceResult
from ..settings import DEFAULT_PRODUCTS


class MockProvider:
    """Deterministic offline provider for fictional assignment data."""

    def classify_content(self, item: ContentItem, products: Sequence[str] = DEFAULT_PRODUCTS) -> RelevanceResult:
        for product in sorted(products, key=len, reverse=True):
            if product and product in item.title:
                return RelevanceResult("relevant", product, f"제목에서 제품명 '{product}' 확인")
            if product and product in item.description:
                return RelevanceResult("relevant", product, f"설명에서 제품명 '{product}' 확인")
            if product and item.matched_product == product:
                return RelevanceResult("relevant", product, f"제품 항목에서 제품명 '{product}' 확인")
        return RelevanceResult("irrelevant", None, "제품명이 확인되지 않아 관련 콘텐츠에서 제외")

    def discover_channels_and_posts(self, hospital: Hospital) -> str:
        return '{"channels":[{"platform":"인스타그램","channel_name":"목업 공식 계정","url":"https://instagram.com/mock-hospital","evidence":"가상 목업 병원 채널","confidence":0.9}],"posts":[{"platform":"인스타그램","title":"울트라클리어 목업 병원 소식","url":"https://instagram.com/p/mock-hospital-1","published_at":"2026-11-01","summary":"울트라클리어 가상 목업 게시물입니다. 실제 병원 정보와 무관합니다.","channel_url":"https://instagram.com/mock-hospital"}]}'

    def summarize_script(self, script_text: str) -> str:
        sentence = script_text.strip().splitlines()[0][:120] if script_text.strip() else ""
        return f"목업 요약: {sentence}" if sentence else ""

    def summarize_hospital(self, hospital: Hospital) -> str:
        region = hospital.region or "지역 정보 미입력"
        contract = hospital.contract_date.isoformat() if hospital.contract_date else "계약일 미입력"
        return f"{hospital.hospital_name}은 {region}에 있으며 계약일은 {contract}입니다."

    def convert_document_to_markdown(self, source_name: str, extracted_text: str) -> str:
        file_name = source_name.replace("\\", "/").rsplit("/", 1)[-1]
        safe_title = file_name.replace("#", "\\#").replace("[", "\\[").replace("]", "\\]")
        content = extracted_text.strip() or "내용이 없습니다."
        return "\n".join((f"# {safe_title}", "", content))
