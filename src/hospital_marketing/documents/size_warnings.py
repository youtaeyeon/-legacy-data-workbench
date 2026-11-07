from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..report import ImportIssue
from .readers import selected_source_files

LARGE_SOURCE_FILE_THRESHOLD_BYTES = 1_000_000
MAX_LARGE_SOURCE_FILE_DETAILS = 5


@dataclass(frozen=True)
class LargeSourceFile:
    file_name: str
    size_bytes: int
    estimated_characters: int


def find_large_source_files(
    source_dir: Path,
    enabled_extensions: Sequence[str],
    *,
    exclude_dir: Path | None = None,
    threshold_bytes: int = LARGE_SOURCE_FILE_THRESHOLD_BYTES,
) -> list[LargeSourceFile]:
    source_dir = Path(source_dir)
    warnings: list[LargeSourceFile] = []
    for source_file in selected_source_files(
        source_dir,
        enabled_extensions,
        exclude_dir=exclude_dir,
    ):
        try:
            size_bytes = source_file.stat().st_size
        except OSError:
            continue
        if size_bytes >= threshold_bytes:
            relative_name = source_file.relative_to(source_dir).as_posix()
            warnings.append(LargeSourceFile(relative_name, size_bytes, size_bytes))
    return sorted(warnings, key=lambda item: (-item.size_bytes, item.file_name.casefold()))


def format_file_size(size_bytes: int) -> str:
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    if size_bytes >= 1_000:
        return f"{size_bytes / 1_000:.1f} KB"
    return f"{size_bytes} B"


def format_large_source_file_list(
    files: Sequence[LargeSourceFile],
    *,
    limit: int = MAX_LARGE_SOURCE_FILE_DETAILS,
) -> str:
    lines = [
        f"• {item.file_name} · {format_file_size(item.size_bytes)} (약 {item.estimated_characters:,}자)"
        for item in files[:limit]
    ]
    if len(files) > limit:
        lines.append(f"외 {len(files) - limit}개")
    return "\n".join(lines)


def format_large_source_file_prompt(files: Sequence[LargeSourceFile]) -> str:
    details = format_large_source_file_list(files)
    return (
        "다음 파일은 크기가 커서 AI 입력 한도를 넘을 수 있습니다. "
        "변환이 실패하거나 사용량 비용이 크게 발생할 수 있습니다.\n"
        f"{details}\n\n계속 진행할까요?"
    )


def large_source_file_issue(file: LargeSourceFile) -> ImportIssue:
    return ImportIssue(
        file.file_name,
        None,
        None,
        None,
        "large_source_file",
        f"파일 크기 {format_file_size(file.size_bytes)} (약 {file.estimated_characters:,}자)로 AI 입력 한도를 넘을 수 있습니다.",
    )
