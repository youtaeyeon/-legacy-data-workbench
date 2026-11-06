"""data/source 날짜별 계약병원 목업이 순서대로 누적 import 되는지 검증."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hospital_marketing.repository import Repository
from hospital_marketing.settings import SettingsStore
from hospital_marketing.workflow import ImportWorkflow

SAMPLE_ROOT = Path(__file__).resolve().parents[1] / "data" / "source"
EXPECTED = (("20261102", 14, 0), ("20261103", 3, 14), ("20261106", 4, 17))


def _snapshot(target):
    repository = Repository(target / "data" / "app.db")
    repository.initialize()
    try:
        hospitals = repository.list_hospitals()
        details = {
            hospital.hospital_id: (
                repository.list_deliveries(hospital.hospital_id),
                repository.list_materials(hospital.hospital_id),
                repository.list_channels(hospital.hospital_id),
                repository.list_contents(hospital.hospital_id),
            )
            for hospital in hospitals
        }
        return hospitals, details
    finally:
        repository.close()


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


def test_root_import_matches_date_ordered_import_of_all_snapshots(tmp_path):
    workflow = ImportWorkflow(SettingsStore(tmp_path / "settings.json"))
    root_target = tmp_path / "root-target"
    sequential_target = tmp_path / "sequential-target"

    root_result = workflow.run(SAMPLE_ROOT, root_target, enabled_extensions=(".xlsx",))
    assert root_result.report.files_seen == 3
    assert root_result.report.files_failed == 0
    assert not {
        "duplicate_hospital_id",
        "unknown_hospital_id",
    } & {issue.code for issue in root_result.report.issues}
    assert root_result.report.inserted_count == 21

    for folder, _, _ in EXPECTED:
        result = workflow.run(SAMPLE_ROOT / folder, sequential_target, enabled_extensions=(".xlsx",))
        assert result.report.files_failed == 0, folder

    assert len(_snapshot(root_target)[0]) == 21
    assert _snapshot(root_target) == _snapshot(sequential_target)
