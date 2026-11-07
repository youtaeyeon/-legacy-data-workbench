from dataclasses import dataclass
from typing import Protocol, Sequence

from ..domain import ContentItem, Hospital


@dataclass(frozen=True)
class RelevanceResult:
    relevance_status: str
    matched_product: str | None
    evidence: str


class AIProvider(Protocol):
    def classify_content(self, item: ContentItem, products: Sequence[str]) -> RelevanceResult: ...

    def summarize_script(self, script_text: str) -> str: ...

    def summarize_hospital(self, hospital: Hospital) -> str: ...

    def convert_document_to_markdown(self, source_name: str, extracted_text: str) -> str: ...
