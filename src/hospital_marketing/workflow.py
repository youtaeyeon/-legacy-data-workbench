from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from collections.abc import Sequence
from typing import Callable

from .ai.registry import ProviderRegistry
from .credentials import CredentialStore
from .documents.conversion import convert_source_documents
from .documents.size_warnings import find_large_source_files, large_source_file_issue
from .domain import Channel, ContentItem, ContentScript
from .channel_discovery import ChannelDiscoveryService, parse_discovery_response
from .providers import ProviderRequestError
from .importer import ImportService
from .outputs.generate import OutputManifest, generate_outputs
from .report import ImportReport
from .repository import Repository
from .settings import SettingsStore


@dataclass(frozen=True)
class WorkflowResult:
    report: ImportReport
    outputs: OutputManifest
    classified_count: int
    needs_review_count: int
    channels_collected: int = 0
    posts_collected: int = 0
    channels_needing_review: int = 0
    channel_failures: int = 0
    channel_discarded: int = 0
    channel_failure_details: tuple[dict[str, str], ...] = ()
    channel_collection_skipped_reason: str = ""
    channel_collection_cancelled: bool = False


class ImportWorkflow:
    def __init__(
        self,
        settings_store: SettingsStore | None = None,
        *,
        repository_factory: Callable[[Path], Repository] = Repository,
        provider_registry: ProviderRegistry | None = None,
        credential_store: CredentialStore | None = None,
    ):
        self.settings_store = settings_store or SettingsStore()
        self.repository_factory = repository_factory
        self.provider_registry = provider_registry or ProviderRegistry()
        self.credential_store = credential_store or CredentialStore()

    def run(
        self,
        source_dir: Path,
        target_dir: Path,
        *,
        provider_id: str = "mock",
        model_id: str = "",
        mock_mode: bool = True,
        enabled_extensions: Sequence[str] | None = None,
        on_progress: Callable[[str], None] | None = None,
        cancel_event=None,
    ) -> WorkflowResult:
        source_dir = Path(source_dir)
        target_dir = Path(target_dir)
        settings = self.settings_store.load()
        extensions = tuple(enabled_extensions) if enabled_extensions is not None else settings.enabled_extensions
        large_source_files = find_large_source_files(
            source_dir,
            extensions,
            exclude_dir=target_dir,
        )
        repository = self.repository_factory(target_dir / "data" / "app.db")
        repository.initialize()
        try:
            existing_ids = {hospital.hospital_id for hospital in repository.list_hospitals()}
            report = ImportService(repository).import_folder(
                source_dir,
                enabled_extensions=extensions,
                exclude_dir=target_dir,
            )
            report.issues.extend(large_source_file_issue(item) for item in large_source_files)
            if mock_mode or provider_id == "mock":
                provider = self.provider_registry.create("mock")
            elif provider_id == "local-cli":
                provider = self.provider_registry.create(provider_id, cli=model_id)
            else:
                api_key = self.credential_store.get(provider_id)
                provider = self.provider_registry.create(provider_id, api_key=api_key or "", model=model_id)

            channels_collected = posts_collected = channels_needing_review = channel_failures = channel_discarded = 0
            failure_details: list[dict[str, str]] = []
            skipped_reason = ""
            collection_cancelled = False
            if settings.auto_collect_hospital_channels:
                discover = getattr(provider, "discover_channels_and_posts", None)
                supported = callable(discover) and (mock_mode or provider_id == "mock" or
                             (provider_id == "local-cli" and model_id == "claude"))
                if not supported:
                    skipped_reason = "자동 수집은 목업 또는 local-cli claude에서만 지원됩니다."
                else:
                    new_hospitals = [hospital for hospital in repository.list_hospitals()
                                     if hospital.hospital_id not in existing_ids]
                    service = ChannelDiscoveryService(repository)
                    for index, hospital in enumerate(new_hospitals, 1):
                        if cancel_event is not None and cancel_event.is_set():
                            collection_cancelled = True
                            break
                        if on_progress:
                            on_progress(f"신규 병원 채널·게시물 수집 중 {index}/{len(new_hospitals)} · {hospital.hospital_name}")
                        try:
                            channels, posts, discarded = parse_discovery_response(discover(hospital))
                            channel_discarded += discarded
                            for candidate in channels:
                                if candidate.confidence >= 0.7:
                                    repository.add_auto_channel(Channel(hospital.hospital_id, candidate.platform,
                                                                        candidate.channel_name, candidate.url))
                                    channels_collected += 1
                                else:
                                    service.save_candidates(hospital.hospital_id, [candidate])
                                    channels_needing_review += 1
                            for post in posts:
                                repository.add_content(ContentItem(hospital.hospital_id, post.platform, post.title,
                                    post.url, post.summary, post.published_at, None, "pending", None))
                                posts_collected += 1
                        except (ProviderRequestError, TimeoutError, OSError) as exc:
                            channel_failures += 1
                            failure_details.append({"hospital_id": hospital.hospital_id,
                                                    "reason": type(exc).__name__})

            classified_count = 0
            needs_review_count = 0
            products = tuple(sorted(
                (keyword.term for keyword in settings.product_keywords if keyword.enabled),
                key=len,
                reverse=True,
            ))
            hospitals = repository.list_hospitals()
            for hospital_index, hospital in enumerate(hospitals, 1):
                contents_to_classify = []
                for content in repository.list_contents(hospital.hospital_id):
                    if content.relevance_status != "pending":
                        if content.relevance_status == "needs_review":
                            needs_review_count += 1
                        continue
                    contents_to_classify.append(content)
                if contents_to_classify:
                    if on_progress:
                        on_progress(f"AI 분류 중 · 병원 {hospital_index}/{len(hospitals)}")
                    batch_method = getattr(provider, "classify_contents", None)
                    results = (batch_method(contents_to_classify, products) if provider_id == "local-cli" and not mock_mode and batch_method
                               else [provider.classify_content(content, products) for content in contents_to_classify])
                    for content, result in zip(contents_to_classify, results):
                        repository.add_content(replace(content, relevance_status=result.relevance_status,
                                                       matched_product=result.matched_product, evidence=result.evidence))
                        classified_count += 1
                        if result.relevance_status == "needs_review":
                            needs_review_count += 1

            for script in repository.list_scripts():
                if script.script_text and not script.summary:
                    repository.upsert_script(replace(script, summary=provider.summarize_script(script.script_text)))

            document_result = convert_source_documents(
                source_dir, target_dir, extensions, provider
            )
            report.source_dir = str(source_dir)
            report.source_files = document_result.source_files
            report.files_seen = document_result.files_seen
            report.documents_converted_count = document_result.files_converted
            structured_failures = {
                issue.file_name
                for issue in report.issues
                if issue.code in {
                    "invalid_workbook",
                    "invalid_csv",
                    "missing_header",
                    "missing_required_columns",
                }
            }
            document_issues = [
                issue
                for issue in document_result.issues
                if issue.file_name not in structured_failures
            ]
            report.files_failed += len({issue.file_name for issue in document_issues})
            report.issues.extend(document_issues)
            outputs = generate_outputs(
                repository,
                target_dir,
                provider,
                registered_products=products,
                import_report=report,
            )
            result = WorkflowResult(report, outputs, classified_count, needs_review_count, channels_collected,
                                    posts_collected, channels_needing_review, channel_failures, channel_discarded,
                                    tuple(failure_details), skipped_reason, collection_cancelled)
            self._write_import_report(report, target_dir, result)
            return result
        finally:
            repository.close()

    @staticmethod
    def _write_import_report(report: ImportReport, target_dir: Path, result: WorkflowResult | None = None) -> Path:
        path = target_dir / "reports" / "last-import.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "source_dir": report.source_dir,
            "source_files": report.source_files,
            "files_seen": report.files_seen,
            "files_failed": report.files_failed,
            "documents_converted_count": report.documents_converted_count,
            "inserted_count": report.inserted_count,
            "updated_count": report.updated_count,
            "unchanged_count": report.unchanged_count,
            "inserted_hospital_ids": report.inserted_hospital_ids,
            "updated_hospital_ids": report.updated_hospital_ids,
            "missing_hospital_ids": report.missing_hospital_ids,
            "issues": [asdict(issue) for issue in report.issues],
            "channel_collection": ({
                "channels_collected": result.channels_collected,
                "posts_collected": result.posts_collected,
                "channels_needing_review": result.channels_needing_review,
                "channel_failures": result.channel_failures,
                "channel_failure_details": list(result.channel_failure_details),
                "channel_discarded": result.channel_discarded,
                "skipped_reason": result.channel_collection_skipped_reason,
                "cancelled": result.channel_collection_cancelled,
            } if result else {}),
        }
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return path
