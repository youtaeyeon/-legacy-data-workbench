from __future__ import annotations

from html import escape
from urllib.parse import urlsplit

from ..ai.base import AIProvider
from ..ai.mock import MockProvider
from ..domain import Channel, ContentItem, EquipmentDelivery, Hospital, MarketingMaterial
from .scripts import NOTICE


def _text(value: object) -> str:
    return escape(str(value if value is not None else "정보 없음"), quote=False).replace("|", "\\|").replace("\n", " ")


def _safe_url(value: str) -> str | None:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or any(char in value for char in "\r\n\t"):
        return None
    return value.strip()


def render_hospital_markdown(
    hospital: Hospital,
    deliveries: list[EquipmentDelivery],
    materials: list[MarketingMaterial],
    channels: list[Channel],
    contents: list[ContentItem],
    provider: AIProvider | None = None,
    *,
    scripts: list[dict] | None = None,
) -> str:
    provider = provider or MockProvider()
    relevant = [item for item in contents if item.relevance_status == "relevant"]
    lines = [
        f"# {_text(hospital.hospital_name)}",
        "",
        f"> {_text(provider.summarize_hospital(hospital))}",
        "",
        "## 기본 정보",
        "",
        f"- 병원 ID: `{_text(hospital.hospital_id)}`",
        f"- 지역: {_text(hospital.region)}",
        f"- 계약일: {_text(hospital.contract_date)}",
        f"- 원본 업데이트: {_text(hospital.source_updated_at)}",
        "",
        "## 납품 장비",
        "",
    ]
    if deliveries:
        lines.extend(["| 장비 | 납품일 | 수량 |", "| --- | --- | ---: |"])
        lines.extend(f"| {_text(item.product_name)} | {_text(item.delivery_date)} | {item.quantity} |" for item in deliveries)
    else:
        lines.append("등록된 납품 장비가 없습니다.")
    lines.extend(["", "## 마케팅 물품", ""])
    if materials:
        lines.extend(["| 장비 | 물품 | 수량 | 상태 |", "| --- | --- | ---: | --- |"])
        lines.extend(f"| {_text(item.product_name)} | {_text(item.material_name)} | {item.quantity} | {_text(item.status)} |" for item in materials)
    else:
        lines.append("등록된 마케팅 물품이 없습니다.")
    lines.extend(["", "## 온라인 채널", ""])
    valid_channels = [channel for channel in channels if _safe_url(channel.url)]
    if valid_channels:
        lines.extend(f"- [{_text(channel.platform)} · {_text(channel.channel_name)}]({_safe_url(channel.url)})" for channel in valid_channels)
    else:
        lines.append("등록된 온라인 채널이 없습니다.")
    lines.extend(["", "## 제품 관련 콘텐츠", ""])
    if relevant:
        for item in relevant:
            url = _safe_url(item.url)
            label = _text(item.title)
            linked_title = f"[{label}]({url})" if url else label
            lines.append(f"- {linked_title} · {_text(item.matched_product)} · {_text(item.evidence)}")
    else:
        lines.append("확인된 제품 관련 콘텐츠가 없습니다.")
    lines.extend(["", "## 스크립트", ""])
    if scripts:
        lines.extend(f"- [{_text(entry['title'])} · {_text(entry['usage_status'])}](../scripts/{entry['path']})" for entry in scripts)
    else:
        lines.append("등록된 콘텐츠 스크립트가 없습니다.")
    lines.extend(["", f"> {NOTICE}"])
    return "\n".join(lines) + "\n"
