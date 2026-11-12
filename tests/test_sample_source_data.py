"""data/source 날짜별 계약병원 목업이 순서대로 누적 import 되는지 검증."""
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hospital_marketing.settings import SettingsStore
from hospital_marketing.workflow import ImportWorkflow

SAMPLE_ROOT = Path(__file__).resolve().parents[1] / "data" / "source"
EXPECTED = (("20261102", 14, 0, 0), ("20261103", 3, 1, 14), ("20261106", 4, 0, 17))


def test_sample_contract_folders_import_incrementally(tmp_path):
    workflow = ImportWorkflow(SettingsStore(tmp_path / "settings.json"))
    target = tmp_path / "target"

    for folder, inserted, updated, unchanged in EXPECTED:
        result = workflow.run(SAMPLE_ROOT / folder, target, enabled_extensions=(".xlsx",))
        report = result.report
        assert report.issues == [], folder
        assert report.files_failed == 0, folder
        assert (report.inserted_count, report.updated_count, report.unchanged_count) == (inserted, updated, unchanged), folder
        assert len(report.inserted_hospital_ids) == inserted, folder
        assert len(report.updated_hospital_ids) == updated, folder
        assert report.missing_hospital_ids == [], folder

    assert len(list((target / "wiki").glob("HM-*.md"))) == 21
    script_index = json.loads((target / "scripts" / "index.json").read_text(encoding="utf-8"))
    assert len(script_index["scripts"]) == 4
    assert {item["usage_status"] for item in script_index["scripts"]} == {"미활용", "제작 중", "게시 완료"}
    assert all(item["content_url"].startswith("https://example.test/") for item in script_index["scripts"])


def test_sample_contract_progress_reports_stages_and_never_moves_backwards(tmp_path):
    progress = []
    workflow = ImportWorkflow(SettingsStore(tmp_path / "settings.json"))

    result = workflow.run(
        SAMPLE_ROOT / "20261102", tmp_path / "target", enabled_extensions=(".xlsx",),
        on_progress=progress.append,
    )

    assert result.report.inserted_count == 14
    assert [item.percent for item in progress] == sorted(item.percent for item in progress)
    assert progress[0].percent == 0
    assert progress[-1].percent == 100
    assert list(dict.fromkeys(item.stage for item in progress)) == [
        "files", "channels", "classification", "outputs"
    ]


def test_root_folder_ignores_nested_snapshots_and_reports_zero_files(tmp_path):
    workflow = ImportWorkflow(SettingsStore(tmp_path / "settings.json"))
    target = tmp_path / "target"

    result = workflow.run(SAMPLE_ROOT, target, enabled_extensions=(".xlsx",))

    assert result.report.files_seen == 0
    assert result.report.files_failed == 0
    assert (result.report.inserted_count, result.report.updated_count, result.report.unchanged_count) == (0, 0, 0)
    assert result.report.issues == []
    assert list((target / "wiki").glob("HM-*.md")) == []
    saved_report = json.loads((target / "reports" / "last-import.json").read_text(encoding="utf-8"))
    assert saved_report["files_seen"] == 0
    assert saved_report["inserted_count"] == 0
