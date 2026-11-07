import json
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from openpyxl import load_workbook

from hospital_marketing.ai.mock import MockProvider
from hospital_marketing.domain import Channel, ContentItem, EquipmentDelivery, Hospital, MarketingMaterial
from hospital_marketing.outputs.generate import generate_outputs
from hospital_marketing.outputs.dashboard import render_dashboard
from hospital_marketing.repository import Repository
from hospital_marketing.settings import DEFAULT_PRODUCTS


def _repository(tmp_path):
    repository = Repository(tmp_path / "app.db")
    repository.initialize()
    repository.upsert_hospital(Hospital("MOCK-001", "목업 병원 001", "가상권역 A", date(2026, 1, 10), datetime(2026, 1, 10, 9, 0)))
    repository.add_delivery(EquipmentDelivery("MOCK-001", "울트라클리어", date(2026, 1, 15), 1))
    repository.add_material(MarketingMaterial("MOCK-001", "울트라클리어", "제품 소개 리플릿", 10, "준비 완료"))
    repository.add_channel(Channel("MOCK-001", "YouTube", "목업 채널", "https://example.test/channel"))
    repository.add_content(ContentItem("MOCK-001", "YouTube", "울트라클리어 소개", "https://example.test/content/1", "목업 제품 소개", date(2026, 3, 1), "울트라클리어", "relevant", "제목의 제품명"))
    repository.add_content(ContentItem("MOCK-001", "YouTube", "병원 일상", "https://example.test/content/2", "무관한 내용", date(2026, 3, 2), None, "irrelevant", "제품명 없음"))
    return repository


def test_generates_hospital_markdown_with_ai_summary_and_related_content_only(tmp_path):
    repository = _repository(tmp_path)

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    markdown = (tmp_path / "target" / "wiki" / "MOCK-001.md").read_text(encoding="utf-8")
    assert "목업 병원 001" in markdown
    assert "가상권역 A" in markdown
    assert "울트라클리어 소개" in markdown
    assert "무관한 내용" not in markdown
    assert manifest.markdown_files == [tmp_path / "target" / "wiki" / "MOCK-001.md"]
    repository.close()


def test_generates_standalone_filterable_html_without_irrelevant_content(tmp_path):
    repository = _repository(tmp_path)

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    html = manifest.dashboard.read_text(encoding="utf-8")
    assert 'id="search-filter"' in html
    assert 'id="product-filter"' in html
    assert 'id="platform-filter"' in html
    assert "addEventListener('input'" in html
    assert "addEventListener('change'" in html
    assert "울트라클리어 소개" in html
    assert "병원 일상" not in html
    assert "<script src=" not in html
    assert 'rel="stylesheet" href=' not in html
    assert "fonts.googleapis.com" not in html
    assert "img.youtube.com" not in html
    assert "example.test/content/1" in html

    class LocalAssetParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.local_references = []

        def handle_starttag(self, tag, attrs):
            for key, value in attrs:
                if key in {"src", "href"} and value:
                    if not urlsplit(value).scheme and not value.startswith("#"):
                        self.local_references.append(value)

    parser = LocalAssetParser()
    parser.feed(html)
    assert parser.local_references == []
    repository.close()


def test_dashboard_uses_reference_layout_and_only_available_hospital_fields(tmp_path):
    repository = _repository(tmp_path)

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    html = manifest.dashboard.read_text(encoding="utf-8")
    assert ".side" in html
    assert "--bg:#ffffff" in html
    assert "prefers-color-scheme:dark" in html
    assert 'data-view="sales"' in html
    assert 'data-view="marketing"' in html
    assert 'data-view="content"' in html
    assert "목업 병원 001" in html
    assert "가상권역 A" in html
    assert "제품 소개 리플릿" in html
    assert "목업 채널" in html
    assert "울트라클리어 소개" in html
    assert "대표명" not in html
    assert "연락처" not in html
    assert "010-3456" not in html
    assert "신상성형외과" not in html
    repository.close()


def test_dashboard_reference_is_preserved_under_docs_design():
    reference = Path(__file__).resolve().parents[1] / "docs" / "design" / "dashboard-reference.html"

    assert reference.is_file()
    html = reference.read_text(encoding="utf-8")
    assert "[AI 참고용 디자인 가이드]" in html
    assert "240px 사이드바" in html


def test_dashboard_reference2_is_preserved_under_docs_design():
    reference = Path(__file__).resolve().parents[1] / "docs" / "design" / "dashboard-reference2.html"

    assert reference.is_file()
    html = reference.read_text(encoding="utf-8")
    assert "콘텐츠 제작" in html
    assert "스크립트 복사" in html


def test_dashboard_keeps_mock_label_and_formats_visible_dates(tmp_path):
    repository = _repository(tmp_path)

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    html = manifest.dashboard.read_text(encoding="utf-8")
    assert "MOCK DATA · MARKETING WIKI" in html
    assert "function formatDate(value" in html
    assert "formatDate(h.contract_date)" in html
    assert "formatDate(items[0].content.published_at" in html
    assert "formatDate(content.published_at" in html
    repository.close()


def test_content_feed_filters_by_content_matched_product_only(tmp_path):
    repository = _repository(tmp_path)

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    html = manifest.dashboard.read_text(encoding="utf-8")
    content_view = html.split("function renderContent(hospitals)", 1)[1].split("function render()", 1)[0]
    assert "const productMatch = !product.value || content.matched_product === product.value;" in content_view
    assert "hospital.products.includes(product.value)" not in content_view
    repository.close()


def test_embedded_html_data_escapes_script_injection(tmp_path):
    repository = _repository(tmp_path)
    repository.add_content(ContentItem("MOCK-001", "YouTube", "</script><img src=x onerror=alert(1)>", "https://example.test/content/xss", "목업", date(2026, 3, 3), "울트라클리어", "relevant", "목업 근거"))

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    html = manifest.dashboard.read_text(encoding="utf-8")
    assert "</script><img src=x" not in html
    assert "\\u003c/script\\u003e" in html
    repository.close()


def test_excel_export_has_expected_sheets_and_neutralizes_formula_text(tmp_path):
    repository = _repository(tmp_path)
    repository.upsert_hospital(Hospital("MOCK-002", "=HYPERLINK(\"https://example.test\")", "가상권역 B"))

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    workbook = load_workbook(manifest.excel, data_only=False)
    assert set(workbook.sheetnames) == {"Hospitals", "Deliveries", "Materials", "Channels", "RelevantContent"}
    cell = workbook["Hospitals"]["B3"]
    assert cell.value.startswith("'")
    assert cell.data_type != "f"
    repository.close()


def test_manifest_contains_target_paths(tmp_path):
    repository = _repository(tmp_path)

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    assert manifest.dashboard == tmp_path / "target" / "dashboard" / "index.html"
    assert manifest.excel == tmp_path / "target" / "exports" / "marketing.xlsx"
    assert manifest.dashboard.is_file()
    assert manifest.excel.is_file()
    repository.close()


def test_dashboard_product_filter_and_registered_products_kpi_use_configured_keywords(tmp_path):
    repository = _repository(tmp_path)
    registered_products = ("제품 A", "제품 B")

    manifest = generate_outputs(
        repository,
        tmp_path / "target",
        MockProvider(),
        registered_products=registered_products,
    )

    html = manifest.dashboard.read_text(encoding="utf-8")
    payload = html.split('id="dashboard-data">', 1)[1].split("</script>", 1)[0]
    data = json.loads(payload)
    assert data["product_keywords"] == list(registered_products)
    assert "for (const value of registeredProducts)" in html
    assert "card('등록 제품', registeredProducts.length" in html
    repository.close()


def test_direct_dashboard_render_defaults_to_existing_products(tmp_path):
    repository = _repository(tmp_path)

    dashboard = render_dashboard(repository, tmp_path / "dashboard.html")

    html = dashboard.read_text(encoding="utf-8")
    payload = html.split('id="dashboard-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(payload)["product_keywords"] == list(DEFAULT_PRODUCTS)
    repository.close()
