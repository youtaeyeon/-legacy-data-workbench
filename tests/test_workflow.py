import json

from hospital_marketing.settings import AppSettings, SettingsStore
from hospital_marketing.workflow import ImportWorkflow
from scripts.create_mock_workbooks import build_fixtures


def test_workflow_initial_and_weekly_runs_persist_and_regenerate_outputs(tmp_path):
    fixtures = tmp_path / "fixtures"
    build_fixtures(fixtures)
    target = tmp_path / "target"
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(AppSettings(source_dir=fixtures / "initial", target_dir=target, mock_mode=True))
    workflow = ImportWorkflow(settings_store=settings)

    first = workflow.run(fixtures / "initial", target)
    second = workflow.run(fixtures / "weekly", target)

    assert (first.report.inserted_count, first.classified_count) == (3, 4)
    assert (second.report.inserted_count, second.report.updated_count, second.report.unchanged_count) == (1, 1, 1)
    assert second.report.missing_hospital_ids == ["MOCK-003"]
    assert second.outputs.dashboard.is_file()
    assert second.outputs.excel.is_file()
    assert len(list((target / "wiki").glob("*.md"))) == 4
    html = second.outputs.dashboard.read_text(encoding="utf-8")
    assert "울트라클리어" in html
    assert "병원 일상 브이로그" not in html
    report = json.loads((target / "reports" / "last-import.json").read_text(encoding="utf-8"))
    assert report["inserted_count"] == 1
    assert "api_key" not in json.dumps(report)


def test_workflow_converts_enabled_documents_to_wiki_markdown(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "weekly-note.txt").write_text("목업 병원 정보", encoding="utf-8")
    (source / "disabled.csv").write_text("hospital_id,hospital_name\\nMOCK-X,제외", encoding="utf-8")
    settings = SettingsStore(tmp_path / "settings.json")
    workflow = ImportWorkflow(settings_store=settings)

    result = workflow.run(source, target, enabled_extensions=(".txt",))

    markdown = target / "wiki" / "source-documents" / "weekly-note_txt.md"
    assert markdown.is_file()
    assert "목업 병원 정보" in markdown.read_text(encoding="utf-8")
    assert not (target / "wiki" / "source-documents" / "disabled_csv.md").exists()
    assert result.report.documents_converted_count == 1
    assert result.report.files_seen == 1
    report = json.loads((target / "reports" / "last-import.json").read_text(encoding="utf-8"))
    assert report["documents_converted_count"] == 1


def test_corrupt_selected_workbook_is_counted_as_one_failed_file(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "broken.xlsx").write_bytes(b"not an xlsx archive")
    workflow = ImportWorkflow(settings_store=SettingsStore(tmp_path / "settings.json"))

    result = workflow.run(source, target, enabled_extensions=(".xlsx",))

    assert result.report.files_seen == 1
    assert result.report.files_failed == 1
    assert len(result.report.issues) == 1
    assert result.report.issues[0].code == "invalid_workbook"


def test_workflow_uses_enabled_product_keywords_for_classification(tmp_path):
    from hospital_marketing.domain import ContentItem, Hospital
    from hospital_marketing.settings import ProductKeyword

    class CapturingProvider:
        def __init__(self):
            self.products = None

        def classify_content(self, item, products):
            self.products = tuple(products)
            from hospital_marketing.ai.base import RelevanceResult
            return RelevanceResult("relevant", "울트라클리어 엘리트", "목업 근거")

        def summarize_hospital(self, hospital):
            return "요약"

        def convert_document_to_markdown(self, source_name, extracted_text):
            return extracted_text

    provider = CapturingProvider()
    class Registry:
        def create(self, *_args, **_kwargs):
            return provider

    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(AppSettings(product_keywords=(
        ProductKeyword("울트라클리어", True),
        ProductKeyword("울트라클리어 엘리트", True),
        ProductKeyword("리뉴비온", False),
    )))
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "target"
    from hospital_marketing.repository import Repository
    repository = Repository(target / "data" / "app.db")
    repository.initialize()
    repository.upsert_hospital(Hospital("MOCK-001", "목업 병원"))
    repository.add_content(ContentItem("MOCK-001", "YouTube", "울트라클리어 엘리트 시술 후기", "https://example.test", "", None, None, "pending", None))
    repository.close()

    ImportWorkflow(settings_store=settings, provider_registry=Registry()).run(source, target)

    assert provider.products == ("울트라클리어 엘리트", "울트라클리어")

def test_workflow_reports_large_source_warning_without_counting_failure(tmp_path):
    from hospital_marketing.documents.size_warnings import LARGE_SOURCE_FILE_THRESHOLD_BYTES

    source = tmp_path / "source"
    source.mkdir()
    (source / "large.txt").write_text("x" * (LARGE_SOURCE_FILE_THRESHOLD_BYTES + 1), encoding="utf-8")
    target = tmp_path / "target"
    result = ImportWorkflow(settings_store=SettingsStore(tmp_path / "settings.json")).run(
        source,
        target,
        enabled_extensions=(".txt",),
    )

    warning = next(issue for issue in result.report.issues if issue.code == "large_source_file")
    saved_report = json.loads((target / "reports" / "last-import.json").read_text(encoding="utf-8"))
    saved_warning = next(issue for issue in saved_report["issues"] if issue["code"] == "large_source_file")
    assert warning.file_name == "large.txt"
    assert "넘을 수 있습니다" in warning.message
    assert result.report.files_failed == 0
    assert saved_warning == {
        "file_name": warning.file_name,
        "sheet": None,
        "row": None,
        "field": None,
        "code": "large_source_file",
        "message": warning.message,
    }
