import json
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from openpyxl import load_workbook

from hospital_marketing.ai.mock import MockProvider
from hospital_marketing.domain import Channel, ContentItem, ContentScript, EquipmentDelivery, Hospital, MarketingMaterial
from hospital_marketing.outputs.generate import generate_outputs
from hospital_marketing.outputs.dashboard import refresh_dashboard, render_dashboard
from hospital_marketing.repository import Repository
from hospital_marketing.report import ImportReport
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


def _dashboard_data(path):
    source = (Path(path).parent / "data.js").read_text(encoding="utf-8")
    return json.loads(source.split("=", 1)[1].strip().removesuffix(";"))


def test_generates_hospital_markdown_with_ai_summary_and_related_content_only(tmp_path):
    repository = _repository(tmp_path)

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    markdown = (tmp_path / "target" / "wiki" / "MOCK-001.md").read_text(encoding="utf-8")
    assert "목업 병원 001" in markdown
    assert "가상권역 A" in markdown
    assert "울트라클리어 소개" in markdown
    assert "무관한 내용" not in markdown
    assert manifest.markdown_files == [tmp_path / "target" / "wiki" / "MOCK-001.md"]


def test_standard_output_generation_refreshes_summary_even_when_cached(tmp_path):
    repository = _repository(tmp_path)
    target = tmp_path / "target"

    class SummaryProvider:
        def __init__(self):
            self.calls = 0

        def summarize_hospital(self, hospital):
            self.calls += 1
            return f"새 요약: {hospital.region}"

    provider = SummaryProvider()
    generate_outputs(repository, target, provider)
    repository.upsert_hospital(Hospital("MOCK-001", "목업 병원 001", "가상권역 B"))
    generate_outputs(repository, target, provider)

    markdown = (target / "wiki" / "MOCK-001.md").read_text(encoding="utf-8")
    assert provider.calls == 2
    assert "> 새 요약: 가상권역 B" in markdown
    assert repository.get_hospital_summary("MOCK-001") == "새 요약: 가상권역 B"
    repository.close()


def test_standard_output_generation_calls_provider_despite_saved_summary(tmp_path):
    repository = _repository(tmp_path)
    repository.save_hospital_summary("MOCK-001", "이전 요약")

    class SummaryProvider:
        def __init__(self):
            self.calls = 0

        def summarize_hospital(self, hospital):
            self.calls += 1
            return "새 요약"

    provider = SummaryProvider()
    generate_outputs(repository, tmp_path / "target", provider)

    assert provider.calls == 1
    assert repository.get_hospital_summary("MOCK-001") == "새 요약"
    repository.close()


def test_generates_standalone_filterable_html_without_irrelevant_content(tmp_path):
    repository = _repository(tmp_path)

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    html = manifest.dashboard.read_text(encoding="utf-8")
    data_js = (manifest.dashboard.parent / "data.js").read_text(encoding="utf-8")
    assert 'id="search-filter"' in html
    assert 'id="product-filter"' in html
    assert 'id="platform-filter"' in html
    assert "addEventListener('input'" in html
    assert "addEventListener('change'" in html
    assert "울트라클리어 소개" in data_js
    assert "병원 일상" not in data_js
    assert '<script src="data.js"></script>' in html
    assert 'rel="stylesheet" href=' not in html
    assert "fonts.googleapis.com" not in html
    assert "img.youtube.com" not in html
    assert "example.test/content/1" in data_js

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
    assert parser.local_references == ["data.js"]
    repository.close()


def test_refresh_dashboard_reads_latest_database_without_provider(tmp_path):
    repository = _repository(tmp_path)
    target = tmp_path / "target"

    path = refresh_dashboard(repository, target, registered_products=("새 제품",))

    payload = _dashboard_data(path)
    assert payload["hospitals"][0]["hospital_name"] == "목업 병원 001"
    assert payload["product_keywords"] == ["새 제품"]
    assert not (target / "wiki").exists()
    assert not (target / "exports").exists()
    repository.close()


def test_dashboard_uses_reference_layout_and_only_available_hospital_fields(tmp_path):
    repository = _repository(tmp_path)
    repository.save_channel_candidate(
        "MOCK-001", "인스타그램", "목업 후보", "https://example.test/pending",
        "목업 확인 근거", 0.8,
    )
    repository.add_channel(Channel("MOCK-001", "위험 채널", "위험 URL", "javascript:alert(1)"))
    repository.upsert_script(ContentScript(
        "https://example.test/content/1", "목업 스크립트", "목업 브리핑 요약", "미활용", date(2026, 3, 3),
    ))

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    html = manifest.dashboard.read_text(encoding="utf-8")
    hospital = _dashboard_data(manifest.dashboard)["hospitals"][0]
    contents = hospital["contents"]
    assert contents[0]["relevance_status"] == "relevant"
    assert contents[0]["usage_status"] == "미활용"
    assert hospital["channel_candidates"][0]["confidence"] == 0.8
    assert hospital["pending_channels"][0]["status"] == "확인 필요"
    assert ".side" in html
    assert "backdrop-filter:blur" in html
    assert "--blue:#7899f5" in html
    assert 'id="hospital-detail"' in html
    assert 'id="hospital-tabs"' in html
    assert 'id="right-rail"' in html
    assert 'data-view="dashboard"' in html
    assert 'data-view="hospitals"' in html
    assert 'data-tab="summary"' in html
    assert 'data-tab="channels"' in html
    assert 'data-tab="collected"' in html
    assert 'data-tab="analysis"' in html
    assert 'data-tab="materials"' in html
    assert 'id="search-filter"' in html and 'id="platform-filter"' in html
    for value in ("목업 병원 001", "가상권역 A", "제품 소개 리플릿", "목업 채널", "울트라클리어 소개", "목업 브리핑 요약", "자동 수집", "확인 필요"):
        assert value in json.dumps(hospital, ensure_ascii=False)
    assert "위험 URL" not in html
    assert "javascript:alert(1)" not in html
    assert 'id="script-modal"' in html and "openScript" in html
    assert "대표명" not in html
    assert "연락처" not in html
    assert "010-3456" not in html
    assert "신상성형외과" not in html
    repository.close()


def test_dashboard_separates_summary_and_hospital_management_and_includes_import_summary(tmp_path):
    repository = _repository(tmp_path)
    report = ImportReport(
        inserted_count=1,
        updated_count=1,
        unchanged_count=2,
        inserted_hospital_ids=["MOCK-002"],
        updated_hospital_ids=["MOCK-001"],
    )
    repository.upsert_hospital(Hospital("MOCK-002", "목업 신규 병원", "가상권역 B"))

    dashboard = render_dashboard(repository, tmp_path / "dashboard.html", import_report=report)

    html = dashboard.read_text(encoding="utf-8")
    data = _dashboard_data(dashboard)
    assert 'id="dashboard-summary"' in html
    assert 'id="hospital-management"' in html
    assert data["import_summary"] == {
        "inserted_count": 1,
        "updated_count": 1,
        "unchanged_count": 2,
        "inserted_hospital_ids": ["MOCK-002"],
        "updated_hospital_ids": ["MOCK-001"],
    }
    assert 'data-view="dashboard"' in html and 'data-view="hospitals"' in html
    assert "채널 확인 필요" in html
    assert "stopImmediatePropagation" not in html
    assert "data-hospital-id" in html
    assert "renderDashboardKpis" in html
    repository.close()


def test_dashboard_motion_supports_view_tabs_lists_modals_counters_and_reduced_motion(tmp_path):
    repository = _repository(tmp_path)

    dashboard = render_dashboard(repository, tmp_path / "dashboard.html")

    html = dashboard.read_text(encoding="utf-8")
    assert html.count("<script>") == 2
    assert "stopImmediatePropagation" not in html
    assert "prefers-reduced-motion:reduce" in html
    assert "matchMedia('(prefers-reduced-motion: reduce)')" in html
    assert "document.startViewTransition" in html
    assert "view-transition-name" in html
    assert 'class="tab-underline"' in html
    assert "requestAnimationFrame" in html and "countUp" in html
    assert "modal-opening" in html and "modal-closing" in html
    assert "animationDelay" in html and "Math.min(index,19)" in html
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
    assert "contract_date" in (manifest.dashboard.parent / "data.js").read_text(encoding="utf-8")
    assert "published_at" in html
    repository.close()


def test_content_feed_filters_by_content_matched_product_only(tmp_path):
    repository = _repository(tmp_path)

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    html = manifest.dashboard.read_text(encoding="utf-8")
    assert '"matched_product"' in (manifest.dashboard.parent / "data.js").read_text(encoding="utf-8")
    assert "renderContents" in html
    repository.close()


def test_embedded_html_data_escapes_script_injection(tmp_path):
    repository = _repository(tmp_path)
    repository.add_content(ContentItem("MOCK-001", "YouTube", "</script><img src=x onerror=alert(1)>", "https://example.test/content/xss", "목업", date(2026, 3, 3), "울트라클리어", "relevant", "목업 근거"))

    manifest = generate_outputs(repository, tmp_path / "target", MockProvider())

    html = manifest.dashboard.read_text(encoding="utf-8")
    data_js = (manifest.dashboard.parent / "data.js").read_text(encoding="utf-8")
    assert "</script><img src=x" not in html + data_js
    assert "\\u003c/script\\u003e" in data_js
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
    data = _dashboard_data(manifest.dashboard)
    assert data["product_keywords"] == list(registered_products)
    assert 'id="product-filter"' in html
    assert "for(const value of registeredProducts)" in html
    assert "['등록 제품',registeredProducts.length]" in html
    repository.close()


def test_direct_dashboard_render_defaults_to_existing_products(tmp_path):
    repository = _repository(tmp_path)

    dashboard = render_dashboard(repository, tmp_path / "dashboard.html")

    html = dashboard.read_text(encoding="utf-8")
    assert _dashboard_data(dashboard)["product_keywords"] == list(DEFAULT_PRODUCTS)
    assert 'id="dashboard-summary"' in html and 'id="hospital-management"' in html
    assert "가져오기 기록이 없습니다." in html
    repository.close()


def test_external_dashboard_data_has_stable_version_and_polling_state_restore(tmp_path):
    repository = _repository(tmp_path)
    dashboard = render_dashboard(repository, tmp_path / "dashboard" / "index.html")
    html = dashboard.read_text(encoding="utf-8")
    data_path = dashboard.parent / "data.js"

    assert data_path.is_file()
    data_js = data_path.read_text(encoding="utf-8")
    payload = json.loads(data_js.split("=", 1)[1].strip().removesuffix(";"))
    assert payload["data_version"]
    assert "window.__DASHBOARD_DATA__" in data_js
    assert 'id="dashboard-data"' not in html
    assert '<script src="data.js"></script>' in html
    assert "data.js?t=" in html and "setInterval" in html and "5000" in html
    assert "sessionStorage" in html and "location.reload()" in html
    assert "scrollX" in html and "scrollY" in html
    repository.close()


def test_dashboard_data_version_changes_only_when_payload_changes(tmp_path):
    repository = _repository(tmp_path)
    dashboard = tmp_path / "dashboard" / "index.html"

    render_dashboard(repository, dashboard)
    data_path = dashboard.parent / "data.js"
    first = json.loads(data_path.read_text(encoding="utf-8").split("=", 1)[1].strip().removesuffix(";"))
    render_dashboard(repository, dashboard)
    same = json.loads(data_path.read_text(encoding="utf-8").split("=", 1)[1].strip().removesuffix(";"))
    repository.upsert_hospital(Hospital("MOCK-002", "목업 신규 병원", "가상권역 B"))
    render_dashboard(repository, dashboard)
    changed = json.loads(data_path.read_text(encoding="utf-8").split("=", 1)[1].strip().removesuffix(";"))

    assert first["data_version"] == same["data_version"]
    assert changed["data_version"] != first["data_version"]
    repository.close()
