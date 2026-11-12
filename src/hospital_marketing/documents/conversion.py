from dataclasses import dataclass, field
import json
from pathlib import Path
from collections.abc import Callable, Sequence

from ..ai.base import AIProvider
from ..report import ImportIssue
from .readers import (
    DocumentExtractionError,
    markdown_output_path,
    read_document,
    selected_source_files,
)


@dataclass
class DocumentConversionResult:
    source_files: list[str] = field(default_factory=list)
    files_seen: int = 0
    files_converted: int = 0
    files_failed: int = 0
    issues: list[ImportIssue] = field(default_factory=list)
    converted_paths: list[Path] = field(default_factory=list)
    cancelled: bool = False


def convert_source_documents(
    source_dir: Path,
    target_dir: Path,
    enabled_extensions: Sequence[str],
    provider: AIProvider,
    *,
    on_progress: Callable[[int, int, str], None] | None = None,
    cancel_event=None,
) -> DocumentConversionResult:
    source_dir = Path(source_dir)
    target_dir = Path(target_dir)
    files = selected_source_files(
        source_dir, enabled_extensions, exclude_dir=target_dir
    )
    result = DocumentConversionResult(files_seen=len(files))
    for index, source_file in enumerate(files, 1):
        if cancel_event is not None and cancel_event.is_set():
            result.cancelled = True
            break
        if on_progress:
            on_progress(index, len(files), source_file.name)
        if cancel_event is not None and cancel_event.is_set():
            result.cancelled = True
            break
        relative_name = source_file.relative_to(source_dir).as_posix()
        result.source_files.append(relative_name)
        try:
            document = read_document(source_file, root=source_dir)
            if not document.text.strip():
                raise DocumentExtractionError(f"추출된 텍스트가 없습니다: {source_file.name}")
            converted = provider.convert_document_to_markdown(
                document.relative_path.as_posix(), document.text
            )
            if not isinstance(converted, str) or not converted.strip():
                raise ValueError("AI가 빈 Markdown 결과를 반환했습니다.")
            metadata = "\n".join(
                (
                    "---",
                    f"source: {json.dumps(document.relative_path.as_posix(), ensure_ascii=False)}",
                    f"format: {json.dumps(document.extension, ensure_ascii=False)}",
                    "---",
                    "",
                )
            )
            output = markdown_output_path(source_dir, target_dir, source_file)
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name(f".{output.name}.tmp")
            temporary.write_text(metadata + converted.strip() + "\n", encoding="utf-8")
            temporary.replace(output)
            result.converted_paths.append(output)
            result.files_converted += 1
        except DocumentExtractionError as exc:
            result.files_failed += 1
            result.issues.append(
                ImportIssue(
                    relative_name,
                    None,
                    None,
                    None,
                    "document_conversion_error",
                    str(exc),
                )
            )
        except Exception:
            result.files_failed += 1
            result.issues.append(
                ImportIssue(
                    relative_name,
                    None,
                    None,
                    None,
                    "document_conversion_error",
                    "문서 Markdown 변환에 실패했습니다. 원본 형식과 AI 설정을 확인해 주세요.",
                )
            )
    return result
