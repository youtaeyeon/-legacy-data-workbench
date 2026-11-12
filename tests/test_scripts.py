import json
from datetime import date

from openpyxl import Workbook, load_workbook

from hospital_marketing.domain import ContentItem, ContentScript, Hospital
from hospital_marketing.importer import ImportService
from hospital_marketing.outputs.generate import generate_outputs
from hospital_marketing.repository import Repository
from hospital_marketing.settings import SettingsStore
from hospital_marketing.workflow import ImportWorkflow


def _repository(tmp_path):
    repository = Repository(tmp_path / "app.db")
    repository.initialize()
    repository.upsert_hospital(Hospital("HM-001", "목업 피부과", "서울", date(2026, 10, 1)))
    repository.add_content(ContentItem(
        "HM-001", "YouTube", "목업 시술", "https://example.test/watch/1", "목업 설명",
        date(2026, 10, 5), "울트라클리어", "relevant", "목업 근거",
    ))
    return repository


def _script_source(tmp_path, *, url="https://example.test/watch/1", status="미활용", text="(샘플) 가상 시술 안내"):
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    path = source / "scripts.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Scripts"
    sheet.append(["content_url", "script_text", "summary", "usage_status", "collected_at"])
    sheet.append([url, text, "가상 소재 요약", status, date(2026, 11, 1)])
    workbook.save(path)
    return source


def test_imports_and_updates_scripts_by_content_url(tmp_path):
    repository = _repository(tmp_path)
    source = _script_source(tmp_path)

    first = ImportService(repository).import_folder(source)
    second = ImportService(repository).import_folder(source)

    scripts = repository.list_scripts()
    assert len(scripts) == 1
    assert scripts[0].content_url == "https://example.test/watch/1"
    assert scripts[0].usage_status == "미활용"
    assert first.updated_count == 0
    assert second.updated_count == 0
    workbook = load_workbook(source / "scripts.xlsx")
    workbook["Scripts"]["D2"] = "제작 중"
    workbook.save(source / "scripts.xlsx")
    changed = ImportService(repository).import_folder(source)
    assert changed.updated_count == 1
    assert repository.list_scripts()[0].usage_status == "제작 중"
    repository.close()


def test_import_reports_unlinked_content_and_invalid_usage_status(tmp_path):
    repository = _repository(tmp_path)
    source = _script_source(tmp_path, status="사용함")
    workbook = load_workbook(source / "scripts.xlsx")
    workbook["Scripts"].append(["https://example.test/missing", "", "", "미활용", date(2026, 11, 1)])
    workbook.save(source / "scripts.xlsx")

    report = ImportService(repository).import_folder(source)

    assert {issue.code for issue in report.issues} >= {"unknown_content_url", "invalid_usage_status"}
    assert repository.list_scripts() == []
    repository.close()


def test_scripts_sheet_is_optional(tmp_path):
    repository = _repository(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Hospitals"
    worksheet.append(["hospital_id", "hospital_name"])
    worksheet.append(["HM-001", "목업 피부과"])
    workbook.save(source / "hospitals.xlsx")

    report = ImportService(repository).import_folder(source)

    assert report.files_failed == 0
    assert not any(issue.sheet == "Scripts" for issue in report.issues)
    repository.close()


def test_generates_deterministic_script_files_index_wiki_links_and_standalone_dashboard(tmp_path):
    repository = _repository(tmp_path)
    source = _script_source(tmp_path)
    ImportService(repository).import_folder(source)
    target = tmp_path / "target"

    generate_outputs(repository, target)
    first_index = (target / "scripts" / "index.json").read_text(encoding="utf-8")
    first_files = sorted(path.relative_to(target / "scripts").as_posix() for path in (target / "scripts").rglob("*.md"))
    generate_outputs(repository, target)

    index = json.loads(first_index)
    assert first_files == ["HM-001/2026-10/20261005_youtube_" + __import__("hashlib").sha1(b"https://example.test/watch/1").hexdigest()[:8] + ".md"]
    assert json.loads((target / "scripts" / "index.json").read_text(encoding="utf-8")) == index
    script = target / "scripts" / first_files[0]
    assert 'content_url: "https://example.test/watch/1"' in script.read_text(encoding="utf-8")
    assert "## 스크립트" in script.read_text(encoding="utf-8")
    assert "스크립트" in (target / "wiki" / "HM-001.md").read_text(encoding="utf-8")
    html = (target / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "✍️ 콘텐츠 제작" in html
    assert "navigator.clipboard" in html
    assert 'id="script-modal"' in html
    assert "openScript=(h,c)" in html
    assert "스크립트 수집 전" in html
    assert "원문에서 보기" in html
    assert "병원 영상·글은 병원의 저작물이므로 SNS 활용 시 사전 허락과 출처 표기가 필요합니다." in html
    assert "target/scripts" not in html
    repository.close()


def test_irrelevant_content_scripts_stay_in_database_but_are_not_exported(tmp_path):
    repository = _repository(tmp_path)
    repository.add_content(ContentItem("HM-001", "Blog", "무관 목업", "https://example.test/irrelevant", "", date(2026, 10, 6), None, "irrelevant", "무관"))
    source = _script_source(tmp_path)
    workbook = load_workbook(source / "scripts.xlsx")
    workbook["Scripts"].append(["https://example.test/irrelevant", "(샘플) 비관련 가상 문장", "", "미활용", date(2026, 11, 1)])
    workbook.save(source / "scripts.xlsx")

    ImportService(repository).import_folder(source)
    generate_outputs(repository, tmp_path / "target")

    assert len(repository.list_scripts()) == 2
    index = json.loads((tmp_path / "target" / "scripts" / "index.json").read_text(encoding="utf-8"))
    assert [item["content_url"] for item in index["scripts"]] == ["https://example.test/watch/1"]
    assert "무관 목업" not in (tmp_path / "target" / "dashboard" / "index.html").read_text(encoding="utf-8")
    repository.close()


def test_script_output_escapes_html_injection_and_only_prunes_managed_folder(tmp_path):
    repository = _repository(tmp_path)
    source = _script_source(tmp_path, text="</script><img onerror=alert(1)>")
    ImportService(repository).import_folder(source)
    target = tmp_path / "target"
    (target / "scripts" / "stale").mkdir(parents=True)
    (target / "scripts" / "stale" / "stale.md").write_text("obsolete", encoding="utf-8")
    (target / "wiki").mkdir()
    (target / "wiki" / "user-note.md").write_text("keep", encoding="utf-8")

    manifest = generate_outputs(repository, target)

    html = manifest.dashboard.read_text(encoding="utf-8")
    assert "</script><img onerror" not in html
    assert "\\u003c/script\\u003e" in html
    assert not (target / "scripts" / "stale" / "stale.md").exists()
    assert (target / "wiki" / "user-note.md").read_text(encoding="utf-8") == "keep"
    repository.close()


def test_workflow_generates_mock_summary_for_script_with_blank_summary(tmp_path):
    target = tmp_path / "target"
    repository = Repository(target / "data" / "app.db")
    repository.initialize()
    repository.upsert_hospital(Hospital("HM-001", "목업 피부과"))
    repository.add_content(ContentItem("HM-001", "YouTube", "목업 소개", "https://example.test/watch/1", "", date(2026, 10, 5), "울트라클리어", "relevant", "목업"))
    repository.upsert_script(ContentScript("https://example.test/watch/1", "(샘플) 가상 문장입니다.", "", "미활용", date(2026, 11, 1)))
    repository.close()
    source = tmp_path / "empty-source"
    source.mkdir()

    ImportWorkflow(SettingsStore(tmp_path / "settings.json")).run(source, target, enabled_extensions=(".xlsx",))

    reopened = Repository(target / "data" / "app.db")
    reopened.initialize()
    assert reopened.list_scripts()[0].summary.startswith("목업 요약:")
    reopened.close()
