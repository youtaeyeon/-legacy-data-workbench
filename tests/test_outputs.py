import json
from datetime import date, datetime

from openpyxl import load_workbook

from hospital_marketing.ai.mock import MockProvider
from hospital_marketing.domain import Channel, ContentItem, EquipmentDelivery, Hospital, MarketingMaterial
from hospital_marketing.outputs.generate import generate_outputs
from hospital_marketing.repository import Repository


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
    assert "example.test/content/1" in html
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
