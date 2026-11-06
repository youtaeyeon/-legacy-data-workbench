import csv
from datetime import date, datetime

from openpyxl import Workbook

from scripts.create_mock_workbooks import build_fixtures
from hospital_marketing.importer import ImportService
from hospital_marketing.repository import Repository


def _service(tmp_path):
    repository = Repository(tmp_path / "target" / "data" / "app.db")
    repository.initialize()
    return repository, ImportService(repository)


def test_initial_import_loads_all_hospitals_and_marketing_details(tmp_path):
    build_fixtures(tmp_path / "fixtures")
    repository, service = _service(tmp_path)

    report = service.import_folder(tmp_path / "fixtures" / "initial")

    assert (report.inserted_count, report.updated_count, report.unchanged_count) == (3, 0, 0)
    assert report.missing_hospital_ids == []
    assert report.issues == []
    assert len(repository.list_hospitals()) == 3
    assert repository.list_deliveries("MOCK-003")[0].product_name == "피아모"
    assert len(repository.list_contents("MOCK-001")) == 2
    repository.close()


def test_weekly_import_adds_updates_and_preserves_missing_existing_hospital(tmp_path):
    build_fixtures(tmp_path / "fixtures")
    repository, service = _service(tmp_path)
    service.import_folder(tmp_path / "fixtures" / "initial")

    report = service.import_folder(tmp_path / "fixtures" / "weekly")

    assert (report.inserted_count, report.updated_count, report.unchanged_count) == (1, 1, 1)
    assert report.missing_hospital_ids == ["MOCK-003"]
    assert repository.get_hospital("MOCK-001").region == "가상권역 D"
    assert repository.get_hospital("MOCK-003") is not None
    assert repository.get_hospital("MOCK-004") is not None
    changes = repository.list_changes("MOCK-001")
    assert {change.field_name for change in changes} == {"region", "source_updated_at"}
    repository.close()


def test_duplicate_ids_are_rejected_without_guessing_but_valid_rows_import(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Hospitals"
    sheet.append(("hospital_id", "hospital_name", "region", "contract_date", "source_updated_at"))
    sheet.append(("MOCK-DUP", "목업 중복 A", "가상권역 A", date(2026, 1, 1), datetime(2026, 1, 1)))
    sheet.append(("MOCK-DUP", "목업 중복 B", "가상권역 B", date(2026, 1, 2), datetime(2026, 1, 2)))
    sheet.append(("MOCK-OK", "목업 정상 병원", "가상권역 C", date(2026, 1, 3), datetime(2026, 1, 3)))
    workbook.save(source / "input.xlsx")
    repository, service = _service(tmp_path)

    report = service.import_folder(source)

    assert report.inserted_count == 1
    assert repository.get_hospital("MOCK-DUP") is None
    assert repository.get_hospital("MOCK-OK") is not None
    assert any(issue.code == "duplicate_hospital_id" for issue in report.issues)
    repository.close()


def test_later_snapshot_overwrites_hospital_fields_from_earlier_file(tmp_path):
    source = tmp_path / "source"
    older = source / "20261102"
    newer = source / "20261103"
    older.mkdir(parents=True)
    newer.mkdir()
    for folder, hospital_name, region in (
        (older, "목업 병원 이전 이름", "가상권역 A"),
        (newer, "목업 병원 최신 이름", "가상권역 B"),
    ):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Hospitals"
        sheet.append(("hospital_id", "hospital_name", "region"))
        sheet.append(("MOCK-SNAPSHOT", hospital_name, region))
        workbook.save(folder / "hospitals.xlsx")
    repository, service = _service(tmp_path)

    report = service.import_folder(source)

    hospital = repository.get_hospital("MOCK-SNAPSHOT")
    assert (report.inserted_count, report.updated_count, report.unchanged_count) == (1, 1, 0)
    assert report.issues == []
    assert hospital is not None
    assert hospital.hospital_name == "목업 병원 최신 이름"
    assert hospital.region == "가상권역 B"
    repository.close()


def test_missing_id_and_invalid_date_are_reported_without_importing_bad_rows(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Hospitals"
    sheet.append(("hospital_id", "hospital_name", "region", "contract_date", "source_updated_at"))
    sheet.append(("", "목업 ID 누락", "가상권역 A", date(2026, 1, 1), datetime(2026, 1, 1)))
    sheet.append(("MOCK-BAD-DATE", "목업 날짜 오류", "가상권역 B", "not-a-date", datetime(2026, 1, 2)))
    sheet.append(("MOCK-GOOD", "목업 정상", "가상권역 C", date(2026, 1, 3), datetime(2026, 1, 3)))
    workbook.save(source / "input.xlsx")
    repository, service = _service(tmp_path)

    report = service.import_folder(source)

    codes = {issue.code for issue in report.issues}
    assert report.inserted_count == 1
    assert {"missing_hospital_id", "invalid_date"} <= codes
    assert repository.get_hospital("MOCK-BAD-DATE") is None
    repository.close()


def test_optional_columns_can_be_absent(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Hospitals"
    sheet.append(("hospital_id", "hospital_name"))
    sheet.append(("MOCK-OPTIONAL", "목업 선택 필드 누락"))
    workbook.save(source / "input.xlsx")
    repository, service = _service(tmp_path)

    report = service.import_folder(source)

    assert report.inserted_count == 1
    hospital = repository.get_hospital("MOCK-OPTIONAL")
    assert hospital.region is None
    assert hospital.contract_date is None
    assert report.issues == []
    repository.close()


def test_database_failure_in_details_rolls_back_hospital_changes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    workbook = Workbook()
    hospitals = workbook.active
    hospitals.title = "Hospitals"
    hospitals.append(("hospital_id", "hospital_name", "region"))
    hospitals.append(("MOCK-ATOMIC", "목업 원자성 병원", "가상권역 A"))
    channels = workbook.create_sheet("Channels")
    channels.append(("hospital_id", "platform", "channel_name", "url"))
    channels.append(("MOCK-ATOMIC", "YouTube", "목업 채널", "https://example.test/atomic"))
    workbook.save(source / "combined.xlsx")
    repository, service = _service(tmp_path)
    repository.connection.execute(
        "CREATE TRIGGER reject_channel BEFORE INSERT ON channels "
        "BEGIN SELECT RAISE(ABORT, 'forced detail failure'); END"
    )

    report = service.import_folder(source)

    assert repository.get_hospital("MOCK-ATOMIC") is None
    assert report.inserted_count == 0
    assert report.files_failed == 1
    assert any(issue.code == "database_error" for issue in report.issues)
    repository.close()


def test_missing_optional_values_do_not_clear_existing_information(tmp_path):
    build_fixtures(tmp_path / "fixtures")
    repository, service = _service(tmp_path)
    service.import_folder(tmp_path / "fixtures" / "initial")
    source = tmp_path / "partial"
    source.mkdir()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Hospitals"
    sheet.append(("hospital_id", "hospital_name"))
    sheet.append(("MOCK-001", "목업 병원 001"))
    workbook.save(source / "partial.xlsx")
    original = repository.get_hospital("MOCK-001")

    report = service.import_folder(source)

    assert report.unchanged_count == 1
    assert repository.get_hospital("MOCK-001").region == original.region
    assert repository.get_hospital("MOCK-001").contract_date == original.contract_date
    assert repository.get_hospital("MOCK-001").source_updated_at == original.source_updated_at
    repository.close()


def test_corrupt_workbook_is_reported_and_does_not_change_database(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "broken.xlsx").write_bytes(b"not an xlsx archive")
    repository, service = _service(tmp_path)

    report = service.import_folder(source)

    assert report.files_failed == 1
    assert len(report.issues) == 1
    assert report.inserted_count == 0
    assert repository.list_hospitals() == []
    repository.close()


def test_csv_hospital_rows_use_the_same_id_based_structured_import(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    csv_path = source / "hospitals.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("hospital_id", "hospital_name", "region", "contract_date"))
        writer.writerow(("MOCK-CSV-001", "CSV 목업 병원", "가상권역 CSV", "2026-10-01"))
    repository, service = _service(tmp_path)

    report = service.import_folder(source, enabled_extensions=(".csv",))

    assert report.files_seen == 1
    assert report.inserted_count == 1
    assert repository.get_hospital("MOCK-CSV-001").region == "가상권역 CSV"
    assert report.issues == []
    repository.close()


def test_disabled_xlsx_is_not_structurally_imported(tmp_path):
    build_fixtures(tmp_path / "fixtures")
    source = tmp_path / "fixtures" / "initial"
    repository, service = _service(tmp_path)

    report = service.import_folder(source, enabled_extensions=(".txt",))

    assert report.files_seen == 0
    assert report.inserted_count == 0
    assert repository.list_hospitals() == []
    repository.close()
