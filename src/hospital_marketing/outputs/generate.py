from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..ai.base import AIProvider
from ..ai.mock import MockProvider
from ..repository import Repository
from .dashboard import render_dashboard
from .excel import export_marketing_excel
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
) -> OutputManifest:
    target_dir = Path(target_dir)
    wiki_dir = target_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    provider = provider or MockProvider()
    markdown_files: list[Path] = []
    for hospital in repository.list_hospitals():
        path = wiki_dir / f"{hospital.hospital_id}.md"
        content = render_hospital_markdown(
            hospital,
            repository.list_deliveries(hospital.hospital_id),
            repository.list_materials(hospital.hospital_id),
            repository.list_channels(hospital.hospital_id),
            repository.list_contents(hospital.hospital_id),
            provider,
        )
        path.write_text(content, encoding="utf-8")
        markdown_files.append(path)
    dashboard = render_dashboard(repository, target_dir / "dashboard" / "index.html")
    excel = export_marketing_excel(repository, target_dir / "exports" / "marketing.xlsx")
    return OutputManifest(markdown_files, dashboard, excel)
