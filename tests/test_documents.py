import csv
import os
from pathlib import Path

import pytest
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches
from reportlab.pdfgen import canvas

from hospital_marketing.documents.readers import (
    DocumentExtractionError,
    SUPPORTED_EXTENSIONS,
    markdown_output_path,
    read_document,
    selected_source_files,
)


def _make_xlsx(path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Hospitals"
    sheet.append(("hospital_id", "hospital_name"))
    sheet.append(("MOCK-101", "목업 병원 101"))
    workbook.save(path)


def _make_csv(path):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("hospital_id", "hospital_name"))
        writer.writerow(("MOCK-102", "목업 병원 102"))


def _make_docx(path):
    document = Document()
    document.add_heading("목업 운영 보고", level=1)
    document.add_paragraph("병원 소개 본문")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "hospital_id"
    table.rows[0].cells[1].text = "hospital_name"
    row = table.add_row().cells
    row[0].text = "MOCK-103"
    row[1].text = "목업 병원 103"
    document.save(path)


def _make_pptx(path):
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    textbox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    textbox.text_frame.text = "목업 발표 본문"
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(6), Inches(1)).table
    table.cell(0, 0).text = "hospital_id"
    table.cell(0, 1).text = "hospital_name"
    table.cell(1, 0).text = "MOCK-104"
    table.cell(1, 1).text = "목업 병원 104"
    presentation.save(path)


def _make_pdf(path, text=None):
    document = canvas.Canvas(str(path))
    if text:
        document.drawString(72, 720, text)
    document.save()


def test_extracts_text_and_tables_from_all_supported_formats(tmp_path):
    files = {
        ".xlsx": tmp_path / "record.xlsx",
        ".csv": tmp_path / "record.csv",
        ".docx": tmp_path / "record.docx",
        ".pptx": tmp_path / "record.pptx",
        ".pdf": tmp_path / "record.pdf",
        ".txt": tmp_path / "record.txt",
        ".md": tmp_path / "record.md",
        ".html": tmp_path / "record.html",
    }
    _make_xlsx(files[".xlsx"])
    _make_csv(files[".csv"])
    _make_docx(files[".docx"])
    _make_pptx(files[".pptx"])
    _make_pdf(files[".pdf"], "MOCK-105 PDF text")
    files[".txt"].write_text("목업 TXT 본문", encoding="utf-8")
    files[".md"].write_text("# 목업 MD 본문", encoding="utf-8")
    files[".html"].write_text("<h1>목업 HTML 본문</h1><script>secret()</script>", encoding="utf-8")

    documents = {extension: read_document(path, root=tmp_path) for extension, path in files.items()}

    assert set(SUPPORTED_EXTENSIONS) == set(files)
    assert "MOCK-101" in documents[".xlsx"].text
    assert "MOCK-102" in documents[".csv"].text
    assert "MOCK-103" in documents[".docx"].text
    assert "MOCK-104" in documents[".pptx"].text
    assert "MOCK-105 PDF text" in documents[".pdf"].text
    assert "목업 TXT 본문" in documents[".txt"].text
    assert "목업 MD 본문" in documents[".md"].text
    assert "목업 HTML 본문" in documents[".html"].text
    assert "secret()" not in documents[".html"].text


def test_scanned_pdf_without_text_layer_reports_clear_error(tmp_path):
    path = tmp_path / "scanned.pdf"
    _make_pdf(path)

    with pytest.raises(DocumentExtractionError, match="텍스트 레이어"):
        read_document(path, root=tmp_path)


def test_extracts_korean_pdf_text_when_a_cjk_font_is_embedded(tmp_path):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    windows_root = Path(os.environ.get("WINDIR", "C:/Windows"))
    fonts = (
        windows_root / "Fonts" / "malgun.ttf",
        Path("/mnt/c/Windows/Fonts/malgun.ttf"),
    )
    font_path = next((path for path in fonts if path.is_file()), None)
    if font_path is None:
        pytest.skip("한글 폰트가 설치된 Windows 환경이 아닙니다.")

    font_name = "HospitalMarketingCJKFixture"
    pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    path = tmp_path / "korean.pdf"
    document = canvas.Canvas(str(path))
    document.setFont(font_name, 10)
    document.drawString(72, 720, "목업 PDF 한글 본문")
    document.save()

    assert "목업 PDF 한글 본문" in read_document(path).text


def test_selected_source_files_uses_only_direct_files_and_ignores_office_temporary_files(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "a.csv").write_text("a,b\n1,2", encoding="utf-8")
    (tmp_path / "b.docx").touch()
    (tmp_path / "nested" / "c.csv").write_text("c,d\n3,4", encoding="utf-8")
    (tmp_path / "~$temporary.csv").write_text("temporary,data", encoding="utf-8")

    selected = selected_source_files(tmp_path, (".csv",))

    assert [path.name for path in selected] == ["a.csv"]


def test_source_scan_excludes_target_subtree_to_prevent_reimporting_generated_outputs(tmp_path):
    source = tmp_path / "source"
    target = source / "target"
    source.mkdir()
    (source / "notes.txt").write_text("source", encoding="utf-8")
    (target / "wiki").mkdir(parents=True)
    (target / "wiki" / "generated.txt").write_text("output", encoding="utf-8")

    selected = selected_source_files(source, (".txt",), exclude_dir=target)
    excluded = selected_source_files(source, (".txt",), exclude_dir=source)

    assert [path.relative_to(source).as_posix() for path in selected] == ["notes.txt"]
    assert excluded == []


def test_markdown_paths_preserve_relative_path_and_extension_to_avoid_collision(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    docx = source / "report.docx"
    pdf = source / "report.pdf"

    docx_path = markdown_output_path(source, target, docx)
    pdf_path = markdown_output_path(source, target, pdf)

    assert docx_path == target / "wiki" / "source-documents" / "report_docx.md"
    assert pdf_path == target / "wiki" / "source-documents" / "report_pdf.md"
    assert docx_path != pdf_path
