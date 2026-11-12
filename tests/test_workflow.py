import json

import pytest

from hospital_marketing.settings import AppSettings, SettingsStore
from hospital_marketing.workflow import ImportWorkflow
from scripts.create_mock_workbooks import build_fixtures


def test_workflow_initial_and_weekly_runs_persist_and_regenerate_outputs(tmp_path):
    fixtures = tmp_path / "fixtures"
    build_fixtures(fixtures)
    target = tmp_path / "target"
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(AppSettings(source_dir=fixtures / "initial", target_dir=target, mock_mode=True,
                             auto_collect_hospital_channels=False))
    workflow = ImportWorkflow(settings_store=settings)

    first = workflow.run(fixtures / "initial", target)
    second = workflow.run(fixtures / "weekly", target)

    assert (first.report.inserted_count, first.classified_count) == (3, 4)
    assert (second.report.inserted_count, second.report.updated_count, second.report.unchanged_count) == (1, 1, 1)
    assert second.report.missing_hospital_ids == ["MOCK-003"]
    assert second.outputs.dashboard.is_file()
    assert second.outputs.excel.is_file()
    assert len(list((target / "wiki").glob("*.md"))) == 4
    html = second.outputs.dashboard.read_text(encoding="utf-8")
    assert "울트라클리어" in html
    assert "병원 일상 브이로그" not in html
    report = json.loads((target / "reports" / "last-import.json").read_text(encoding="utf-8"))
    assert report["inserted_count"] == 1
    assert "api_key" not in json.dumps(report)


def test_mock_workflow_collects_channels_and_recent_posts_only_for_new_hospitals(tmp_path):
    from hospital_marketing.repository import Repository

    fixtures = tmp_path / "fixtures"
    build_fixtures(fixtures)
    target = tmp_path / "target"
    workflow = ImportWorkflow(settings_store=SettingsStore(tmp_path / "settings.json"))

    first = workflow.run(fixtures / "initial", target, mock_mode=True)
    second = workflow.run(fixtures / "weekly", target, mock_mode=True)

    assert (first.channels_collected, first.posts_collected) == (3, 3)
    assert (second.channels_collected, second.posts_collected) == (1, 1)
    repository = Repository(target / "data" / "app.db")
    repository.initialize()
    assert len(repository.list_channels("MOCK-001")) == 2
    assert len(repository.list_contents("MOCK-001")) == 3
    source = repository.connection.execute(
        "SELECT source FROM channels WHERE hospital_id='MOCK-001' AND url='https://instagram.com/mock-hospital'"
    ).fetchone()[0]
    repository.close()
    assert source == "자동 수집"
    report = json.loads((target / "reports" / "last-import.json").read_text(encoding="utf-8"))
    assert report["channel_collection"]["channels_collected"] == 1
    assert "목업 병원 소식" in (target / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "목업 병원 소식" in (target / "wiki" / "MOCK-001.md").read_text(encoding="utf-8")


def test_workflow_cancel_event_stops_before_next_hospital(tmp_path):
    from threading import Event
    from hospital_marketing.ai.registry import ProviderRegistry
    from hospital_marketing.ai.mock import MockProvider

    fixtures = tmp_path / "fixtures"
    build_fixtures(fixtures)
    cancel = Event()
    calls = []
    class CancellingProvider(MockProvider):
        def discover_channels_and_posts(self, hospital):
            calls.append(hospital.hospital_id)
            return super().discover_channels_and_posts(hospital)
    registry = ProviderRegistry({"mock": lambda **_: CancellingProvider()})
    result = ImportWorkflow(settings_store=SettingsStore(tmp_path / "settings.json"), provider_registry=registry).run(
        fixtures / "initial", tmp_path / "target", mock_mode=True, cancel_event=cancel,
        on_progress=lambda progress: cancel.set() if progress.stage == "channels" else None)
    assert len(calls) == 1
    assert result.channel_collection_cancelled


def test_workflow_cancellation_skips_classification_and_regenerates_outputs(tmp_path):
    from threading import Event
    from hospital_marketing.ai.base import RelevanceResult
    from hospital_marketing.domain import ContentItem, Hospital
    from hospital_marketing.repository import Repository

    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    repository = Repository(target / "data" / "app.db")
    repository.initialize()
    repository.upsert_hospital(Hospital("MOCK-001", "목업 병원"))
    repository.add_content(ContentItem("MOCK-001", "YouTube", "제목", "https://example.test", "", None, None, "pending", None))
    repository.close()

    class Provider:
        classify_calls = 0
        summarize_calls = 0
        def classify_content(self, *_args):
            self.classify_calls += 1
            return RelevanceResult("relevant", "제품", "근거")
        def summarize_script(self, *_args):
            self.summarize_calls += 1
            return "요약"
        def summarize_hospital(self, *_args): return "요약"
        def convert_document_to_markdown(self, _name, text): return text

    provider = Provider()
    class Registry:
        def create(self, *_args, **_kwargs): return provider

    cancel = Event()
    result = ImportWorkflow(settings_store=SettingsStore(tmp_path / "settings.json"), provider_registry=Registry()).run(
        source, target, cancel_event=cancel,
        on_progress=lambda item: cancel.set() if item.stage == "classification" else None,
    )

    assert result.cancelled_stage == "classification"
    assert provider.classify_calls == provider.summarize_calls == 0
    assert result.outputs.dashboard.is_file()
    assert result.outputs.excel.is_file()
    assert (target / "wiki" / "MOCK-001.md").is_file()


def test_dashboard_includes_current_app_generator_metadata(tmp_path):
    from hospital_marketing.version import APP_VERSION
    from hospital_marketing.repository import Repository

    target = tmp_path / "target"
    repository = Repository(target / "data" / "app.db")
    repository.initialize()
    result = ImportWorkflow(settings_store=SettingsStore(tmp_path / "settings.json")).run(tmp_path / "source", target)
    repository.close()
    html = result.outputs.dashboard.read_text(encoding="utf-8")
    assert f'<meta name="generator" content="hospital-marketing {APP_VERSION}">' in html


def test_channel_discovery_failure_is_recorded_and_other_hospitals_continue(tmp_path):
    from hospital_marketing.ai.registry import ProviderRegistry
    from hospital_marketing.ai.mock import MockProvider
    from hospital_marketing.providers import ProviderRequestError

    fixtures = tmp_path / "fixtures"
    build_fixtures(fixtures)
    class FailingProvider(MockProvider):
        def discover_channels_and_posts(self, hospital):
            if hospital.hospital_id == "MOCK-001":
                raise ProviderRequestError("provider unavailable")
            return super().discover_channels_and_posts(hospital)
    target = tmp_path / "target"
    result = ImportWorkflow(settings_store=SettingsStore(tmp_path / "settings.json"),
                            provider_registry=ProviderRegistry({"mock": lambda **_: FailingProvider()})).run(
        fixtures / "initial", target, mock_mode=True)
    report = json.loads((target / "reports" / "last-import.json").read_text(encoding="utf-8"))
    assert result.channel_failures == 1
    assert report["channel_collection"]["channel_failure_details"] == [
        {"hospital_id": "MOCK-001", "reason": "ProviderRequestError"}]
    assert result.channels_collected > 0


def test_low_confidence_channel_is_pending_and_visible_in_wiki_and_dashboard(tmp_path):
    from hospital_marketing.ai.mock import MockProvider
    from hospital_marketing.ai.registry import ProviderRegistry

    fixtures = tmp_path / "fixtures"
    build_fixtures(fixtures)
    class LowConfidenceProvider(MockProvider):
        def discover_channels_and_posts(self, hospital):
            return '{"channels":[{"platform":"인스타그램","channel_name":"확인 계정","url":"https://instagram.com/mock-pending","evidence":"목업 근거","confidence":0.6}],"posts":[]}'
    target = tmp_path / "target"
    result = ImportWorkflow(settings_store=SettingsStore(tmp_path / "settings.json"),
                            provider_registry=ProviderRegistry({"mock": lambda **_: LowConfidenceProvider()})).run(
        fixtures / "initial", target, mock_mode=True)
    assert result.channels_needing_review == 3
    dashboard = (target / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "확인 계정" in dashboard
    assert "channel_candidates.map" in dashboard
    wiki = (target / "wiki" / "MOCK-001.md").read_text(encoding="utf-8")
    assert "### 확인 필요" in wiki
    assert "확인 계정" in wiki


def test_non_claude_local_cli_reports_auto_collection_skip(tmp_path):
    from hospital_marketing.ai.mock import MockProvider
    from hospital_marketing.ai.registry import ProviderRegistry
    fixtures = tmp_path / "fixtures"
    build_fixtures(fixtures)
    result = ImportWorkflow(settings_store=SettingsStore(tmp_path / "settings.json"),
                            provider_registry=ProviderRegistry({"local-cli": lambda **_: MockProvider()})).run(
        fixtures / "initial", tmp_path / "target", provider_id="local-cli", model_id="codex", mock_mode=False)
    assert result.channel_failures == 0
    assert "local-cli claude" in result.channel_collection_skipped_reason
    report = json.loads((tmp_path / "target" / "reports" / "last-import.json").read_text(encoding="utf-8"))
    assert report["channel_collection"]["skipped_reason"]


def test_workflow_converts_enabled_documents_to_wiki_markdown(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "weekly-note.txt").write_text("목업 병원 정보", encoding="utf-8")
    (source / "disabled.csv").write_text("hospital_id,hospital_name\\nMOCK-X,제외", encoding="utf-8")
    settings = SettingsStore(tmp_path / "settings.json")
    workflow = ImportWorkflow(settings_store=settings)

    result = workflow.run(source, target, enabled_extensions=(".txt",))

    markdown = target / "wiki" / "source-documents" / "weekly-note_txt.md"
    assert markdown.is_file()
    assert "목업 병원 정보" in markdown.read_text(encoding="utf-8")
    assert not (target / "wiki" / "source-documents" / "disabled_csv.md").exists()
    assert result.report.documents_converted_count == 1
    assert result.report.files_seen == 1
    report = json.loads((target / "reports" / "last-import.json").read_text(encoding="utf-8"))
    assert report["documents_converted_count"] == 1
    assert report["source_dir"] == str(source)
    assert report["source_files"] == ["weekly-note.txt"]


def test_corrupt_selected_workbook_is_counted_as_one_failed_file(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "broken.xlsx").write_bytes(b"not an xlsx archive")
    workflow = ImportWorkflow(settings_store=SettingsStore(tmp_path / "settings.json"))

    result = workflow.run(source, target, enabled_extensions=(".xlsx",))

    assert result.report.files_seen == 1
    assert result.report.files_failed == 1
    assert len(result.report.issues) == 1
    assert result.report.issues[0].code == "invalid_workbook"


def test_workflow_uses_enabled_product_keywords_for_classification(tmp_path):
    from hospital_marketing.domain import ContentItem, Hospital
    from hospital_marketing.settings import ProductKeyword

    class CapturingProvider:
        def __init__(self):
            self.products = None

        def classify_content(self, item, products):
            self.products = tuple(products)
            from hospital_marketing.ai.base import RelevanceResult
            return RelevanceResult("relevant", "울트라클리어 엘리트", "목업 근거")

        def summarize_hospital(self, hospital):
            return "요약"

        def convert_document_to_markdown(self, source_name, extracted_text):
            return extracted_text

    provider = CapturingProvider()
    class Registry:
        def create(self, *_args, **_kwargs):
            return provider

    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(AppSettings(product_keywords=(
        ProductKeyword("울트라클리어", True),
        ProductKeyword("울트라클리어 엘리트", True),
        ProductKeyword("리뉴비온", False),
    )))
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "target"
    from hospital_marketing.repository import Repository
    repository = Repository(target / "data" / "app.db")
    repository.initialize()
    repository.upsert_hospital(Hospital("MOCK-001", "목업 병원"))
    repository.add_content(ContentItem("MOCK-001", "YouTube", "울트라클리어 엘리트 시술 후기", "https://example.test", "", None, None, "pending", None))
    repository.close()

    ImportWorkflow(settings_store=settings, provider_registry=Registry()).run(source, target)

    assert provider.products == ("울트라클리어 엘리트", "울트라클리어")


@pytest.mark.parametrize("provider_id,mock_mode,use_batch", [
    ("local-cli", False, True),
    ("openai", False, False),
    ("local-cli", True, False),
])
def test_workflow_selects_expected_classification_method_and_reports_progress(tmp_path, provider_id, mock_mode, use_batch):
    from hospital_marketing.ai.base import RelevanceResult
    from hospital_marketing.domain import ContentItem, Hospital
    from hospital_marketing.repository import Repository

    class FakeProvider:
        def __init__(self):
            self.single_calls = []
            self.batch_calls = []

        def classify_content(self, item, products):
            self.single_calls.append(item)
            return RelevanceResult("relevant", "제품", "단건 근거")

        def classify_contents(self, items, products):
            self.batch_calls.append(tuple(items))
            return [RelevanceResult("relevant", "제품", "일괄 근거") for _item in items]

        def summarize_script(self, text):
            return "요약"

        def summarize_hospital(self, hospital):
            return "요약"

        def convert_document_to_markdown(self, source_name, text):
            return text

    provider = FakeProvider()

    class Registry:
        def create(self, *_args, **_kwargs):
            return provider

    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    repository = Repository(target / "data" / "app.db")
    repository.initialize()
    repository.upsert_hospital(Hospital("MOCK-001", "목업 병원"))
    item = ContentItem("MOCK-001", "YouTube", "제목", "https://example.test", "", None, None, "pending", None)
    repository.add_content(item)
    repository.close()
    progress = []

    ImportWorkflow(
        settings_store=SettingsStore(tmp_path / "settings.json"), provider_registry=Registry(),
        credential_store=type("Credentials", (), {"get": lambda self, _provider_id: "test-key"})(),
    ).run(source, target, provider_id=provider_id, mock_mode=mock_mode, on_progress=progress.append)

    assert bool(provider.batch_calls) is use_batch
    assert bool(provider.single_calls) is not use_batch
    classification_progress = next(item for item in progress if item.stage == "classification")
    assert classification_progress.current == 1
    assert classification_progress.total == 1
    assert classification_progress.percent >= 50
    saved = Repository(target / "data" / "app.db")
    saved.initialize()
    classified = saved.list_contents("MOCK-001")[0]
    saved.close()
    assert classified.relevance_status == "relevant"
    assert classified.evidence == ("일괄 근거" if use_batch else "단건 근거")


def test_workflow_progress_uses_monotonic_percentages_and_four_ordered_stages(tmp_path):
    fixtures = tmp_path / "fixtures"
    build_fixtures(fixtures)
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(AppSettings(auto_collect_hospital_channels=True))
    progress = []

    ImportWorkflow(settings_store=settings).run(
        fixtures / "initial", tmp_path / "target", mock_mode=True,
        on_progress=progress.append,
    )

    percentages = [item.percent for item in progress]
    stages = [item.stage for item in progress]
    assert percentages[0] == 0
    assert percentages == sorted(percentages)
    assert percentages[-1] == 100
    assert stages == sorted(stages, key=("files", "channels", "classification", "outputs").index)


def test_import_folder_reports_each_file_progress(tmp_path):
    from hospital_marketing.importer import ImportService
    from hospital_marketing.repository import Repository

    fixtures = tmp_path / "fixtures"
    build_fixtures(fixtures)
    repository = Repository(tmp_path / "target" / "data" / "app.db")
    repository.initialize()
    progress = []

    ImportService(repository).import_folder(
        fixtures / "initial", on_progress=lambda current, total, name: progress.append((current, total, name))
    )

    assert progress
    assert progress[-1][0] == progress[-1][1]
    assert all(1 <= current <= total for current, total, _ in progress)
    repository.close()

def test_workflow_reports_large_source_warning_without_counting_failure(tmp_path):
    from hospital_marketing.documents.size_warnings import LARGE_SOURCE_FILE_THRESHOLD_BYTES

    source = tmp_path / "source"
    source.mkdir()
    (source / "large.txt").write_text("x" * (LARGE_SOURCE_FILE_THRESHOLD_BYTES + 1), encoding="utf-8")
    target = tmp_path / "target"
    result = ImportWorkflow(settings_store=SettingsStore(tmp_path / "settings.json")).run(
        source,
        target,
        enabled_extensions=(".txt",),
    )

    warning = next(issue for issue in result.report.issues if issue.code == "large_source_file")
    saved_report = json.loads((target / "reports" / "last-import.json").read_text(encoding="utf-8"))
    saved_warning = next(issue for issue in saved_report["issues"] if issue["code"] == "large_source_file")
    assert warning.file_name == "large.txt"
    assert "넘을 수 있습니다" in warning.message
    assert result.report.files_failed == 0
    assert saved_warning == {
        "file_name": warning.file_name,
        "sheet": None,
        "row": None,
        "field": None,
        "code": "large_source_file",
        "message": warning.message,
    }
