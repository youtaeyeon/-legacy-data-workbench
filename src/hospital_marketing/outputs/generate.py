from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence

from ..ai.base import AIProvider
from ..ai.mock import MockProvider
from ..repository import Repository
from ..report import ImportReport
from ..settings import DEFAULT_PRODUCTS
from .dashboard import render_dashboard
from .excel import export_marketing_excel
from .scripts import generate_scripts
from .markdown import render_hospital_markdown


@dataclass(frozen=True)
class OutputManifest:
    markdown_files: list[Path]
    dashboard: Path
    excel: Path


def generate_outputs(
    repository: Repository,
    target_dir: Path,
    provider: AIProvider | None = None,
    *,
    registered_products: Sequence[str] = DEFAULT_PRODUCTS,
    import_report: ImportReport | None = None,
) -> OutputManifest:
    target_dir = Path(target_dir)
    wiki_dir = target_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    provider = provider or MockProvider()
    markdown_files: list[Path] = []
    script_entries = generate_scripts(repository, target_dir)
    scripts_by_hospital: dict[str, list[dict]] = {}
    for entry in script_entries:
        scripts_by_hospital.setdefault(entry["hospital_id"], []).append(entry)
    for hospital in repository.list_hospitals():
        path = wiki_dir / f"{hospital.hospital_id}.md"
        content = render_hospital_markdown(
            hospital,
            repository.list_deliveries(hospital.hospital_id),
            repository.list_materials(hospital.hospital_id),
            repository.list_channels(hospital.hospital_id),
            repository.list_contents(hospital.hospital_id),
            provider,
            scripts=scripts_by_hospital.get(hospital.hospital_id, []),
            channel_candidates=[dict(row) for row in repository.list_channel_candidates(hospital.hospital_id, "pending")],
        )
        path.write_text(content, encoding="utf-8")
        markdown_files.append(path)
    dashboard = render_dashboard(
        repository,
        target_dir / "dashboard" / "index.html",
        registered_products=registered_products,
        import_report=import_report,
    )
    excel = export_marketing_excel(repository, target_dir / "exports" / "marketing.xlsx")
    return OutputManifest(markdown_files, dashboard, excel)
