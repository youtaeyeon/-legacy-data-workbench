from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import csv
import io

from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from . import SUPPORTED_EXTENSIONS


class DocumentExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class ExtractedDocument:
    path: Path
    relative_path: Path
    extension: str
    text: str


class _VisibleHTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self.parts.append(data.strip())


def _decode_text(raw: bytes, filename: str) -> str:
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise DocumentExtractionError(f"텍스트 파일을 읽을 수 없습니다: {filename}") from exc


def _cell_text(value: object) -> str:
    return str(value).replace("|", r"\|").replace("\r", " ").replace("\n", " ") if value is not None else ""


def _table_markdown(rows: Sequence[Sequence[object]]) -> str:
    normalized = [[_cell_text(value) for value in row] for row in rows]
    while normalized and not any(normalized[-1]):
        normalized.pop()
    if not normalized:
        return ""
    width = max(len(row) for row in normalized)
    normalized = [row + [""] * (width - len(row)) for row in normalized]
    header = normalized[0]
    divider = ["---"] * width
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(divider) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in normalized[1:])
    return "\n".join(lines)


def _read_xlsx(path: Path) -> str:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sections: list[str] = []
    try:
        for sheet in workbook.worksheets:
            rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            rendered = _table_markdown(rows)
            if rendered:
                sections.extend((f"## {sheet.title}", rendered))
    finally:
        workbook.close()
    return "\n\n".join(sections)


def _read_csv(path: Path) -> str:
    raw = path.read_bytes()
    text = _decode_text(raw, path.name)
    rows = list(csv.reader(io.StringIO(text, newline="")))
    return _table_markdown(rows)


def _read_docx(path: Path) -> str:
    document = Document(path)
    parts = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        rendered = _table_markdown([[cell.text for cell in row.cells] for row in table.rows])
        if rendered:
            parts.append(rendered)
    return "\n\n".join(parts)


def _read_pptx(path: Path) -> str:
    presentation = Presentation(path)
    slides: list[str] = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = shape.text.strip()
                if text:
                    parts.append(text)
            if getattr(shape, "has_table", False):
                table = shape.table
                rendered = _table_markdown(
                    [[cell.text for cell in row.cells] for row in table.rows]
                )
                if rendered:
                    parts.append(rendered)
        if parts:
            slides.append(f"## 슬라이드 {slide_number}\n\n" + "\n\n".join(parts))
    return "\n\n".join(slides)


def _read_pdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise DocumentExtractionError(f"PDF를 읽을 수 없습니다: {path.name}") from exc
    content = [f"## 페이지 {number}\n\n{text.strip()}" for number, text in enumerate(pages, 1) if text.strip()]
    if not content:
        raise DocumentExtractionError(f"텍스트 레이어가 없는 PDF입니다: {path.name}")
    return "\n\n".join(content)


def read_document(path: Path, root: Path | None = None) -> ExtractedDocument:
    path = Path(path)
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentExtractionError(f"지원하지 않는 파일 형식입니다: {path.name}")
    try:
        relative_path = path.resolve().relative_to(Path(root).resolve()) if root else Path(path.name)
    except ValueError as exc:
        raise DocumentExtractionError(f"원본 폴더 밖의 파일은 읽을 수 없습니다: {path.name}") from exc
    try:
        if extension == ".xlsx":
            text = _read_xlsx(path)
        elif extension == ".csv":
            text = _read_csv(path)
        elif extension == ".docx":
            text = _read_docx(path)
        elif extension == ".pptx":
            text = _read_pptx(path)
        elif extension == ".pdf":
            text = _read_pdf(path)
        elif extension in {".txt", ".md"}:
            text = _decode_text(path.read_bytes(), path.name).strip()
        else:
            parser = _VisibleHTMLText()
            parser.feed(_decode_text(path.read_bytes(), path.name))
            text = "\n".join(parser.parts)
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError(f"파일을 읽을 수 없습니다: {path.name}") from exc
    return ExtractedDocument(path, relative_path, extension, text)


def selected_source_files(
    source_dir: Path,
    enabled_extensions: Sequence[str],
    *,
    exclude_dir: Path | None = None,
) -> list[Path]:
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        return []
    enabled = {
        extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        for extension in enabled_extensions
    } & set(SUPPORTED_EXTENSIONS)
    source_root = source_dir.resolve()
    excluded = Path(exclude_dir).resolve() if exclude_dir is not None else None
    files: list[Path] = []
    for path in source_dir.iterdir():
        if not path.is_file() or path.name.startswith("~$") or path.suffix.lower() not in enabled:
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(source_root):
            continue
        if excluded is not None and resolved.is_relative_to(excluded):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(source_dir).as_posix().casefold())


def markdown_output_path(source_dir: Path, target_dir: Path, source_file: Path) -> Path:
    relative = Path(source_file).resolve().relative_to(Path(source_dir).resolve())
    extension = relative.suffix.lower().lstrip(".")
    markdown_name = f"{relative.stem}_{extension}.md"
    return Path(target_dir) / "wiki" / "source-documents" / relative.parent / markdown_name
