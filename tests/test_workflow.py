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
