from pathlib import Path

from hospital_marketing.documents.size_warnings import (
    LARGE_SOURCE_FILE_THRESHOLD_BYTES,
    LargeSourceFile,
    find_large_source_files,
    format_file_size,
    format_large_source_file_list,
    format_large_source_file_prompt,
)


def test_size_scan_warns_only_for_over_threshold_selected_direct_files(tmp_path):
    source = tmp_path / "source"
    target = source / "target"
    nested = source / "nested"
    target.mkdir(parents=True)
    nested.mkdir()
    (source / "above.txt").write_bytes(b"x" * (LARGE_SOURCE_FILE_THRESHOLD_BYTES + 1))
    (source / "at-limit.txt").write_bytes(b"x" * LARGE_SOURCE_FILE_THRESHOLD_BYTES)
    (source / "below.txt").write_bytes(b"x" * (LARGE_SOURCE_FILE_THRESHOLD_BYTES - 1))
    (source / "ignored.csv").write_bytes(b"x" * (LARGE_SOURCE_FILE_THRESHOLD_BYTES + 5))
    (nested / "nested.txt").write_bytes(b"x" * (LARGE_SOURCE_FILE_THRESHOLD_BYTES + 9))
    (target / "generated.txt").write_bytes(b"x" * (LARGE_SOURCE_FILE_THRESHOLD_BYTES + 11))

    files = find_large_source_files(source, (".txt",), exclude_dir=target)

    assert files == [
        LargeSourceFile("above.txt", LARGE_SOURCE_FILE_THRESHOLD_BYTES + 1, LARGE_SOURCE_FILE_THRESHOLD_BYTES + 1),
        LargeSourceFile("at-limit.txt", LARGE_SOURCE_FILE_THRESHOLD_BYTES, LARGE_SOURCE_FILE_THRESHOLD_BYTES),
    ]


def test_size_format_and_file_list_limit_to_five_and_report_remainder():
    assert format_file_size(999) == "999 B"
    assert format_file_size(12_345) == "12.3 KB"
    assert format_file_size(2_300_000) == "2.3 MB"
    files = [LargeSourceFile(f"file-{index}.csv", 2_300_000 - index, 2_300_000 - index) for index in range(6)]

    details = format_large_source_file_list(files)

    assert details.splitlines()[:2] == [
        "• file-0.csv · 2.3 MB (약 2,300,000자)",
        "• file-1.csv · 2.3 MB (약 2,299,999자)",
    ]
    assert details.splitlines()[-1] == "외 1개"
    prompt = format_large_source_file_prompt(files[:1])
    assert "AI 입력 한도를 넘을 수 있습니다" in prompt
    assert "변환이 실패하거나 사용량 비용이 크게 발생할 수 있습니다" in prompt
    assert "계속 진행할까요?" in prompt
