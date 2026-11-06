from pathlib import Path

from hospital_marketing.ai.mock import MockProvider
from hospital_marketing.documents.conversion import convert_source_documents


def test_only_direct_source_files_are_ai_formatted_as_wiki_markdown(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "nested").mkdir(parents=True)
    text_file = source / "report.txt"
    text_file.write_text("병원에 관한 사실만 보존합니다.", encoding="utf-8")
    nested_file = source / "nested" / "nested.txt"
    nested_file.write_text("하위 폴더 문서는 제외합니다.", encoding="utf-8")
    (source / "report.csv").write_text("ignored,data\n1,2", encoding="utf-8")
    original = text_file.read_bytes()

    result = convert_source_documents(source, target, (".txt",), MockProvider())

    output = target / "wiki" / "source-documents" / "report_txt.md"
    assert result.files_seen == 1
    assert result.files_converted == 1
    assert result.files_failed == 0
    assert result.issues == []
    assert result.converted_paths == [output]
    assert output.is_file()
    markdown = output.read_text(encoding="utf-8")
    assert 'source: "report.txt"' in markdown
    assert "# report.txt" in markdown
    assert "병원에 관한 사실만 보존합니다." in markdown
    assert text_file.read_bytes() == original
    assert not (target / "wiki" / "source-documents" / "nested" / "nested_txt.md").exists()
    assert nested_file.read_text(encoding="utf-8") == "하위 폴더 문서는 제외합니다."


def test_unreadable_selected_documents_are_reported_without_markdown_output(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    from reportlab.pdfgen import canvas

    pdf = source / "scan.pdf"
    canvas.Canvas(str(pdf)).save()

    result = convert_source_documents(source, target, (".pdf",), MockProvider())

    assert result.files_seen == 1
    assert result.files_converted == 0
    assert result.files_failed == 1
    assert result.issues[0].file_name == "scan.pdf"
    assert result.issues[0].code == "document_conversion_error"
    assert "텍스트 레이어" in result.issues[0].message
    assert not (target / "wiki" / "source-documents" / "scan_pdf.md").exists()
