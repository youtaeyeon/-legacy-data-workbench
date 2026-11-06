"""data/source 날짜별 계약병원 목업이 순서대로 누적 import 되는지 검증."""
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hospital_marketing.settings import SettingsStore
from hospital_marketing.workflow import ImportWorkflow

SAMPLE_ROOT = Path(__file__).resolve().parents[1] / "data" / "source"
EXPECTED = (("20261102", 14, 0), ("20261103", 3, 14), ("20261106", 4, 17))


def test_sample_contract_folders_import_incrementally(tmp_path):
    workflow = ImportWorkflow(SettingsStore(tmp_path / "settings.json"))
    target = tmp_path / "target"

    for folder, inserted, unchanged in EXPECTED:
        result = workflow.run(SAMPLE_ROOT / folder, target, enabled_extensions=(".xlsx",))
        report = result.report
        assert report.issues == [], folder
        assert report.files_failed == 0, folder
        assert (report.inserted_count, report.updated_count, report.unchanged_count) == (inserted, 0, unchanged), folder
        assert report.missing_hospital_ids == [], folder

    assert len(list((target / "wiki").glob("HM-*.md"))) == 21


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
