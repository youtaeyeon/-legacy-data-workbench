from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from collections.abc import Sequence
from typing import Callable

from .ai.registry import ProviderRegistry
from .credentials import CredentialStore
from .documents.conversion import convert_source_documents
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
    ) -> WorkflowResult:
        source_dir = Path(source_dir)
        target_dir = Path(target_dir)
        settings = self.settings_store.load()
        extensions = tuple(enabled_extensions) if enabled_extensions is not None else settings.enabled_extensions
        repository = self.repository_factory(target_dir / "data" / "app.db")
        repository.initialize()
        try:
            report = ImportService(repository).import_folder(
                source_dir,
                enabled_extensions=extensions,
                exclude_dir=target_dir,
            )
            if mock_mode or provider_id == "mock":
                provider = self.provider_registry.create("mock")
            else:
                api_key = self.credential_store.get(provider_id)
                provider = self.provider_registry.create(provider_id, api_key=api_key or "", model=model_id)

            classified_count = 0
            needs_review_count = 0
            products = tuple(sorted(
                (keyword.term for keyword in settings.product_keywords if keyword.enabled),
                key=len,
                reverse=True,
            ))
            for hospital in repository.list_hospitals():
                for content in repository.list_contents(hospital.hospital_id):
                    if content.relevance_status != "pending":
                        if content.relevance_status == "needs_review":
                            needs_review_count += 1
                        continue
                    result = provider.classify_content(content, products)
                    repository.add_content(replace(
                        content,
                        relevance_status=result.relevance_status,
                        matched_product=result.matched_product,
                        evidence=result.evidence,
                    ))
                    classified_count += 1
                    if result.relevance_status == "needs_review":
                        needs_review_count += 1

            document_result = convert_source_documents(
                source_dir, target_dir, extensions, provider
            )
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
            )
            self._write_import_report(report, target_dir)
            return WorkflowResult(report, outputs, classified_count, needs_review_count)
        finally:
            repository.close()

    @staticmethod
    def _write_import_report(report: ImportReport, target_dir: Path) -> Path:
        path = target_dir / "reports" / "last-import.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "files_seen": report.files_seen,
            "files_failed": report.files_failed,
            "documents_converted_count": report.documents_converted_count,
            "inserted_count": report.inserted_count,
            "updated_count": report.updated_count,
            "unchanged_count": report.unchanged_count,
            "missing_hospital_ids": report.missing_hospital_ids,
            "issues": [asdict(issue) for issue in report.issues],
        }
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return path
