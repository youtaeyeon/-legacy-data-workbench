from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

HOSPITAL_HEADERS = (
    "hospital_id",
    "hospital_name",
    "region",
    "contract_date",
    "source_updated_at",
)

INITIAL_HOSPITALS = (
    ("MOCK-001", "목업 병원 001", "가상권역 A", date(2026, 1, 10), datetime(2026, 1, 10, 9, 0)),
    ("MOCK-002", "목업 병원 002", "가상권역 B", date(2026, 2, 12), datetime(2026, 2, 12, 9, 0)),
    ("MOCK-003", "목업 병원 003", "가상권역 C", date(2026, 3, 14), datetime(2026, 3, 14, 9, 0)),
)

WEEKLY_HOSPITALS = (
    ("MOCK-001", "목업 병원 001", "가상권역 D", date(2026, 1, 10), datetime(2026, 4, 1, 9, 0)),
    ("MOCK-002", "목업 병원 002", "가상권역 B", date(2026, 2, 12), datetime(2026, 2, 12, 9, 0)),
    ("MOCK-004", "목업 병원 004", "가상권역 D", date(2026, 4, 1), datetime(2026, 4, 1, 9, 0)),
)

DETAIL_SHEETS = {
    "Deliveries": (
        ("hospital_id", "product_name", "delivery_date", "quantity"),
        ("MOCK-001", "울트라클리어", date(2026, 1, 15), 1),
        ("MOCK-002", "리뉴비온", date(2026, 2, 20), 2),
        ("MOCK-003", "피아모", date(2026, 3, 20), 1),
        ("MOCK-004", "피아모", date(2026, 4, 5), 1),
    ),
    "Materials": (
        ("hospital_id", "product_name", "material_name", "quantity", "status"),
        ("MOCK-001", "울트라클리어", "제품 소개 리플릿", 10, "준비 완료"),
        ("MOCK-002", "리뉴비온", "진료실 안내 카드", 5, "준비 중"),
        ("MOCK-003", "피아모", "초기 상담 안내 자료", 4, "준비 완료"),
        ("MOCK-004", "피아모", "제품 안내 포스터", 2, "준비 완료"),
    ),
    "Channels": (
        ("hospital_id", "platform", "channel_name", "url"),
        ("MOCK-001", "YouTube", "목업 병원 001 채널", "https://example.test/mock-001/youtube"),
        ("MOCK-002", "Blog", "목업 병원 002 블로그", "https://example.test/mock-002/blog"),
        ("MOCK-003", "Instagram", "목업 병원 003 계정", "https://example.test/mock-003/instagram"),
        ("MOCK-004", "Instagram", "목업 병원 004 계정", "https://example.test/mock-004/instagram"),
    ),
    "ContentCandidates": (
        ("hospital_id", "platform", "title", "url", "description", "published_at", "matched_product", "expected_relevance"),
        ("MOCK-001", "YouTube", "울트라클리어 소개", "https://example.test/content/001", "울트라클리어 사용 안내 목업 영상", date(2026, 3, 1), "울트라클리어", "relevant"),
        ("MOCK-002", "Blog", "리뉴비온 활용 사례", "https://example.test/content/002", "리뉴비온 관련 가상 게시물", date(2026, 3, 2), "리뉴비온", "relevant"),
        ("MOCK-003", "Instagram", "피아모 콘텐츠 안내", "https://example.test/content/003", "피아모 제품 관련 가상 게시물", date(2026, 3, 3), "피아모", "relevant"),
        ("MOCK-004", "Instagram", "피아모 사용 안내", "https://example.test/content/004", "피아모 제품 관련 가상 게시물", date(2026, 4, 2), "피아모", "relevant"),
        ("MOCK-001", "YouTube", "병원 일상 브이로그", "https://example.test/content/005", "장비와 무관한 가상 병원 일상 콘텐츠", date(2026, 4, 3), "", "irrelevant"),
    ),
}


def _write_workbook(path: Path, sheets: dict[str, tuple[tuple, ...]]) -> None:
    workbook = Workbook()
    default_sheet = workbook.active
    if default_sheet is not None:
        workbook.remove(default_sheet)
    for title, rows in sheets.items():
        worksheet = workbook.create_sheet(title)
        for row in rows:
            worksheet.append(row)
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
    workbook.save(path)


def build_fixtures(output_dir: Path) -> None:
    """Create deterministic, fictional initial and weekly Excel source folders."""
    snapshots = (
        ("initial", "initial_hospitals.xlsx", INITIAL_HOSPITALS),
        ("weekly", "weekly_update.xlsx", WEEKLY_HOSPITALS),
    )
    for folder_name, workbook_name, hospital_rows in snapshots:
        source_dir = output_dir / folder_name
        source_dir.mkdir(parents=True, exist_ok=True)
        _write_workbook(
            source_dir / workbook_name,
            {"Hospitals": (HOSPITAL_HEADERS, *hospital_rows)},
        )
        included_ids = {row[0] for row in hospital_rows}
        details = {
            sheet_name: (rows[0], *(row for row in rows[1:] if row[0] in included_ids))
            for sheet_name, rows in DETAIL_SHEETS.items()
        }
        _write_workbook(source_dir / "marketing_details.xlsx", details)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    build_fixtures(project_root / "fixtures" / "source")
