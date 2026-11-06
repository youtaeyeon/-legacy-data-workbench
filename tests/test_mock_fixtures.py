from openpyxl import load_workbook

from scripts.create_mock_workbooks import build_fixtures


def _rows(path, sheet):
    workbook = load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook[sheet]
    values = list(worksheet.iter_rows(values_only=True))
    headers = values[0]
    return [dict(zip(headers, row)) for row in values[1:]]


def test_builds_initial_and_weekly_workbooks_with_required_sheets_and_headers(tmp_path):
    build_fixtures(tmp_path)

    initial = tmp_path / "initial" / "initial_hospitals.xlsx"
    weekly = tmp_path / "weekly" / "weekly_update.xlsx"
    details = tmp_path / "initial" / "marketing_details.xlsx"
    assert initial.is_file()
    assert weekly.is_file()
    assert details.is_file()

    initial_rows = _rows(initial, "Hospitals")
    assert {"hospital_id", "hospital_name", "region", "contract_date", "source_updated_at"} <= set(initial_rows[0])
    assert len(initial_rows) == 3

    weekly_rows = _rows(weekly, "Hospitals")
    assert {row["hospital_id"] for row in weekly_rows} == {"MOCK-001", "MOCK-002", "MOCK-004"}

    workbook = load_workbook(details, read_only=True, data_only=True)
    assert set(workbook.sheetnames) == {"Deliveries", "Materials", "Channels", "ContentCandidates"}


def test_weekly_fixture_has_one_new_one_changed_and_one_unchanged_hospital(tmp_path):
    build_fixtures(tmp_path)
    initial = {row["hospital_id"]: row for row in _rows(tmp_path / "initial" / "initial_hospitals.xlsx", "Hospitals")}
    weekly = {row["hospital_id"]: row for row in _rows(tmp_path / "weekly" / "weekly_update.xlsx", "Hospitals")}

    assert "MOCK-004" not in initial and "MOCK-004" in weekly
    assert initial["MOCK-001"]["region"] != weekly["MOCK-001"]["region"]
    assert initial["MOCK-002"] == weekly["MOCK-002"]


def test_content_fixture_covers_all_products_and_irrelevant_items(tmp_path):
    build_fixtures(tmp_path)
    contents = _rows(tmp_path / "initial" / "marketing_details.xlsx", "ContentCandidates")
    joined = " ".join(str(value) for row in contents for value in row.values())

    assert all(product in joined for product in ("울트라클리어", "리뉴비온", "피아모"))
    assert any(row["expected_relevance"] == "irrelevant" for row in contents)
    assert all(row["url"].startswith("https://example.test/") for row in contents)
