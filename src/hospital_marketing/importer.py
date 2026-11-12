from __future__ import annotations

import csv
import io
import sqlite3
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

from .diff import compare_hospital
from .documents.readers import selected_source_files
from .domain import Channel, ContentItem, ContentScript, EquipmentDelivery, Hospital, MarketingMaterial
from .report import ImportIssue, ImportReport
from .repository import Repository

DETAIL_SHEETS = ("Deliveries", "Materials", "Channels", "ContentCandidates", "Scripts")
USAGE_STATUSES = {"미활용", "제작 중", "게시 완료"}


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    raise ValueError("날짜 형식이 올바르지 않습니다")


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        text = value.strip()
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return datetime.combine(date.fromisoformat(text), datetime.min.time())
    raise ValueError("날짜/시간 형식이 올바르지 않습니다")


def _headers(values: tuple[Any, ...]) -> dict[str, int]:
    return {str(value).strip().lower(): index for index, value in enumerate(values) if value is not None and str(value).strip()}


def _cell(row: tuple[Any, ...], headers: dict[str, int], name: str) -> Any:
    index = headers.get(name)
    return row[index] if index is not None and index < len(row) else None


def _value_text(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)


_CSV_SHEETS = (
    ("Hospitals", {"hospital_id", "hospital_name"}),
    ("Materials", {"hospital_id", "product_name", "material_name", "quantity", "status"}),
    ("Deliveries", {"hospital_id", "product_name", "quantity"}),
    ("Channels", {"hospital_id", "platform", "channel_name", "url"}),
    ("ContentCandidates", {"hospital_id", "platform", "title", "url"}),
    ("Scripts", {"content_url"}),
)


def _csv_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _csv_sheet_name(header_row: list[str]) -> str:
    headers = {value.strip().lower() for value in header_row if value.strip()}
    for sheet_name, required in _CSV_SHEETS:
        if required <= headers:
            return sheet_name
    return "Data"


def _load_source_workbook(path: Path) -> Any:
    if path.suffix.lower() != ".csv":
        return load_workbook(path, read_only=True, data_only=True)
    rows = list(csv.reader(io.StringIO(_csv_text(path), newline="")))
    workbook = Workbook()
    worksheet = workbook.active
    if worksheet is None:
        worksheet = workbook.create_sheet()
    worksheet.title = _csv_sheet_name(rows[0]) if rows else "Data"
    for row in rows:
        worksheet.append(row)
    return workbook


class ImportService:
    def __init__(self, repository: Repository):
        self.repository = repository

    def import_folder(
        self,
        source_dir: Path,
        *,
        enabled_extensions: Sequence[str] | None = None,
        exclude_dir: Path | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> ImportReport:
        report = ImportReport()
        source_dir = Path(source_dir)
        if not source_dir.is_dir():
            report.issues.append(ImportIssue(source_dir.name, None, None, None, "source_dir_missing", "원본 폴더를 찾을 수 없습니다."))
            return report

        enabled = enabled_extensions if enabled_extensions is not None else (".xlsx", ".csv")
        structured_extensions = tuple(
            extension
            for extension in enabled
            if extension.lower().lstrip(".") in {"xlsx", "csv"}
        )
        files = selected_source_files(
            source_dir, structured_extensions, exclude_dir=exclude_dir
        )
        report.files_seen = len(files)
        readable_files: list[Path] = []
        candidate_rows: list[tuple[str, Hospital, str, int]] = []
        has_snapshot = False

        for index, path in enumerate(files, 1):
            if on_progress:
                on_progress(index, len(files), path.name)
            file_name = path.relative_to(source_dir).as_posix()
            try:
                workbook = _load_source_workbook(path)
            except Exception:
                report.files_failed += 1
                is_csv = path.suffix.lower() == ".csv"
                code = "invalid_csv" if is_csv else "invalid_workbook"
                kind = "CSV" if is_csv else "Excel"
                report.issues.append(ImportIssue(file_name, None, None, None, code, f"{kind} 파일을 읽을 수 없습니다."))
                continue
            readable_files.append(path)
            try:
                if "Hospitals" not in workbook.sheetnames:
                    continue
                has_snapshot = True
                worksheet = workbook["Hospitals"]
                iterator = worksheet.iter_rows(values_only=True)
                header_values = next(iterator, None)
                if not header_values:
                    report.files_failed += 1
                    report.issues.append(ImportIssue(file_name, "Hospitals", 1, None, "missing_header", "헤더 행이 비어 있습니다."))
                    continue
                headers = _headers(header_values)
                missing_headers = {"hospital_id", "hospital_name"} - headers.keys()
                if missing_headers:
                    report.files_failed += 1
                    report.issues.append(ImportIssue(file_name, "Hospitals", 1, None, "missing_required_columns", f"필수 열 누락: {', '.join(sorted(missing_headers))}"))
                    continue
                for row_number, row in enumerate(iterator, start=2):
                    if not any(value is not None and value != "" for value in row):
                        continue
                    hospital_id_raw = _cell(row, headers, "hospital_id")
                    hospital_id = str(hospital_id_raw).strip() if hospital_id_raw is not None else ""
                    if not hospital_id:
                        report.issues.append(ImportIssue(file_name, "Hospitals", row_number, "hospital_id", "missing_hospital_id", "병원 ID가 비어 있어 행을 건너뛰었습니다."))
                        continue
                    hospital_name_raw = _cell(row, headers, "hospital_name")
                    hospital_name = str(hospital_name_raw).strip() if hospital_name_raw is not None else ""
                    if not hospital_name:
                        report.issues.append(ImportIssue(file_name, "Hospitals", row_number, "hospital_name", "missing_hospital_name", "병원명이 비어 있어 행을 건너뛰었습니다."))
                        continue
                    try:
                        contract_date = _parse_date(_cell(row, headers, "contract_date"))
                        source_updated_at = _parse_datetime(_cell(row, headers, "source_updated_at"))
                    except (TypeError, ValueError) as exc:
                        report.issues.append(ImportIssue(file_name, "Hospitals", row_number, "date", "invalid_date", str(exc)))
                        continue
                    hospital = Hospital(
                        hospital_id=hospital_id,
                        hospital_name=hospital_name,
                        region=str(_cell(row, headers, "region")).strip() if _cell(row, headers, "region") not in (None, "") else None,
                        contract_date=contract_date,
                        source_updated_at=source_updated_at,
                    )
                    candidate_rows.append((hospital_id, hospital, file_name, row_number))
            finally:
                workbook.close()

        counts = Counter((file_name, hospital_id) for hospital_id, _, file_name, _ in candidate_rows)
        duplicate_ids = {
            (file_name, hospital_id)
            for (file_name, hospital_id), count in counts.items()
            if count > 1
        }
        for hospital_id, _, file_name, row_number in candidate_rows:
            if (file_name, hospital_id) in duplicate_ids:
                report.issues.append(ImportIssue(file_name, "Hospitals", row_number, "hospital_id", "duplicate_hospital_id", f"파일 안에서 병원 ID {hospital_id}가 여러 번 있어 해당 ID의 행을 모두 건너뛰었습니다."))
        incoming = [
            (hospital, file_name, row_number)
            for hospital_id, hospital, file_name, row_number in candidate_rows
            if (file_name, hospital_id) not in duplicate_ids
        ]

        if has_snapshot:
            stored_ids = {hospital.hospital_id for hospital in self.repository.list_hospitals()}
            incoming_ids = {hospital.hospital_id for hospital, _, _ in incoming}
            report.missing_hospital_ids = sorted(stored_ids - incoming_ids)

        try:
            with self.repository.transaction():
                self._apply_hospitals(incoming, report)
                self._import_details(readable_files, report, source_dir)
        except sqlite3.Error:
            report.inserted_count = 0
            report.updated_count = 0
            report.unchanged_count = 0
            report.inserted_hospital_ids.clear()
            report.updated_hospital_ids.clear()
            report.files_failed += 1
            report.issues.append(ImportIssue(source_dir.name, None, None, None, "database_error", "저장 중 데이터베이스 오류가 발생해 이번 가져오기 전체를 취소했습니다."))
        except Exception:
            report.inserted_count = 0
            report.updated_count = 0
            report.unchanged_count = 0
            report.inserted_hospital_ids.clear()
            report.updated_hospital_ids.clear()
            report.files_failed += 1
            report.issues.append(ImportIssue(source_dir.name, None, None, None, "import_error", "가져오기 중 예상하지 못한 오류가 발생해 이번 가져오기 전체를 취소했습니다."))
        return report

    def _apply_hospitals(self, incoming: list[tuple[Hospital, str, int]], report: ImportReport) -> None:
        for incoming_hospital, _, _ in incoming:
            stored = self.repository.get_hospital(incoming_hospital.hospital_id)
            if stored is None:
                self.repository.upsert_hospital(incoming_hospital)
                report.inserted_count += 1
                if incoming_hospital.hospital_id not in report.inserted_hospital_ids:
                    report.inserted_hospital_ids.append(incoming_hospital.hospital_id)
                continue
            merged = Hospital(
                hospital_id=incoming_hospital.hospital_id,
                hospital_name=incoming_hospital.hospital_name,
                region=incoming_hospital.region if incoming_hospital.region is not None else stored.region,
                contract_date=incoming_hospital.contract_date if incoming_hospital.contract_date is not None else stored.contract_date,
                source_updated_at=incoming_hospital.source_updated_at if incoming_hospital.source_updated_at is not None else stored.source_updated_at,
            )
            changes = compare_hospital(merged, stored)
            if not changes:
                report.unchanged_count += 1
                continue
            self.repository.upsert_hospital(merged)
            for change in changes:
                self.repository.record_change(change)
            report.updated_count += 1
            if incoming_hospital.hospital_id not in report.updated_hospital_ids:
                report.updated_hospital_ids.append(incoming_hospital.hospital_id)

    def _import_details(
        self, files: list[Path], report: ImportReport, source_dir: Path
    ) -> None:
        required_columns = {
            "Deliveries": {"hospital_id", "product_name", "quantity"},
            "Materials": {"hospital_id", "product_name", "material_name", "quantity", "status"},
            "Channels": {"hospital_id", "platform", "channel_name", "url"},
            "ContentCandidates": {"hospital_id", "platform", "title", "url"},
            "Scripts": {"content_url"},
        }
        for path in files:
            file_name = path.relative_to(source_dir).as_posix()
            workbook = _load_source_workbook(path)
            try:
                for sheet_name in DETAIL_SHEETS:
                    if sheet_name not in workbook.sheetnames:
                        continue
                    worksheet = workbook[sheet_name]
                    iterator = worksheet.iter_rows(values_only=True)
                    header_values = next(iterator, None)
                    if not header_values:
                        report.issues.append(ImportIssue(file_name, sheet_name, 1, None, "missing_header", "시트 헤더가 비어 있습니다."))
                        continue
                    headers = _headers(header_values)
                    missing_headers = required_columns[sheet_name] - headers.keys()
                    if missing_headers:
                        report.issues.append(ImportIssue(file_name, sheet_name, 1, None, "missing_required_columns", f"필수 열 누락: {', '.join(sorted(missing_headers))}"))
                        continue
                    for row_number, row in enumerate(iterator, start=2):
                        if not any(value is not None and value != "" for value in row):
                            continue
                        if sheet_name == "Scripts":
                            raw_status = _cell(row, headers, "usage_status")
                            status = str(raw_status).strip() if raw_status not in (None, "") else "미활용"
                            if status not in USAGE_STATUSES:
                                report.issues.append(ImportIssue(file_name, sheet_name, row_number, "usage_status", "invalid_usage_status", "활용 상태는 미활용, 제작 중, 게시 완료 중 하나여야 합니다."))
                                continue
                            content_url_raw = _cell(row, headers, "content_url")
                            content_url = str(content_url_raw).strip() if content_url_raw is not None else ""
                            linked = self.repository.connection.execute("SELECT hospital_id FROM contents WHERE url=?", (content_url,)).fetchone() if content_url else None
                            if not linked:
                                report.issues.append(ImportIssue(file_name, sheet_name, row_number, "content_url", "unknown_content_url", "연결된 콘텐츠 URL을 찾을 수 없어 행을 건너뛰었습니다."))
                                continue
                            try:
                                changed = self.repository.upsert_script(ContentScript(
                                    content_url, str(_cell(row, headers, "script_text") or "").strip(),
                                    str(_cell(row, headers, "summary") or "").strip(), status,
                                    _parse_date(_cell(row, headers, "collected_at")),
                                ))
                                if changed:
                                    report.updated_count += 1
                                    hospital_id = linked["hospital_id"]
                                    if hospital_id not in report.updated_hospital_ids:
                                        report.updated_hospital_ids.append(hospital_id)
                            except (TypeError, ValueError) as exc:
                                report.issues.append(ImportIssue(file_name, sheet_name, row_number, None, "invalid_value", str(exc)))
                            continue
                        hospital_id_raw = _cell(row, headers, "hospital_id")
                        hospital_id = str(hospital_id_raw).strip() if hospital_id_raw is not None else ""
                        if not hospital_id:
                            report.issues.append(ImportIssue(file_name, sheet_name, row_number, "hospital_id", "missing_hospital_id", "병원 ID가 비어 있어 행을 건너뛰었습니다."))
                            continue
                        if self.repository.get_hospital(hospital_id) is None:
                            report.issues.append(ImportIssue(file_name, sheet_name, row_number, "hospital_id", "unknown_hospital_id", f"등록되지 않은 병원 ID {hospital_id}라 행을 건너뛰었습니다."))
                            continue
                        try:
                            if sheet_name == "Deliveries":
                                quantity = int(_cell(row, headers, "quantity"))
                                self.repository.add_delivery(EquipmentDelivery(hospital_id, str(_cell(row, headers, "product_name")).strip(), _parse_date(_cell(row, headers, "delivery_date")), quantity))
                            elif sheet_name == "Materials":
                                quantity = int(_cell(row, headers, "quantity"))
                                self.repository.add_material(MarketingMaterial(hospital_id, str(_cell(row, headers, "product_name")).strip(), str(_cell(row, headers, "material_name")).strip(), quantity, str(_cell(row, headers, "status")).strip()))
                            elif sheet_name == "Channels":
                                self.repository.add_channel(Channel(hospital_id, str(_cell(row, headers, "platform")).strip(), str(_cell(row, headers, "channel_name")).strip(), str(_cell(row, headers, "url")).strip()))
                            else:
                                published_at = _parse_date(_cell(row, headers, "published_at"))
                                matched_product = _cell(row, headers, "matched_product")
                                self.repository.add_content(ContentItem(
                                    hospital_id=hospital_id,
                                    platform=str(_cell(row, headers, "platform")).strip(),
                                    title=str(_cell(row, headers, "title")).strip(),
                                    url=str(_cell(row, headers, "url")).strip(),
                                    description=str(_cell(row, headers, "description") or "").strip(),
                                    published_at=published_at,
                                    matched_product=str(matched_product).strip() if matched_product not in (None, "") else None,
                                    relevance_status="pending",
                                    evidence=None,
                                ))
                        except (TypeError, ValueError) as exc:
                            report.issues.append(ImportIssue(file_name, sheet_name, row_number, None, "invalid_value", str(exc)))
            finally:
                workbook.close()
