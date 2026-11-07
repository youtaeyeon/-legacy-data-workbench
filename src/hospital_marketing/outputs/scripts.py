from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..domain import ContentItem, ContentScript, Hospital
from ..repository import Repository

NOTICE = "병원 영상·글은 병원의 저작물이므로 SNS 활용 시 사전 허락과 출처 표기가 필요합니다. 스크립트는 소재 발굴·참고용입니다."


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", value.lower()).strip("_") or "unknown"


def _hospital_folder(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "unknown"


def _yaml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _file_content(hospital: Hospital, content: ContentItem, script: ContentScript) -> str:
    fields = {
        "content_url": content.url,
        "hospital_id": hospital.hospital_id,
        "hospital_name": hospital.hospital_name,
        "platform": content.platform,
        "title": content.title,
        "published_at": content.published_at.isoformat() if content.published_at else "",
        "product": content.matched_product or "",
        "usage_status": script.usage_status,
        "collected_at": script.collected_at.isoformat() if script.collected_at else "",
    }
    frontmatter = "\n".join(f"{key}: {_yaml(value)}" for key, value in fields.items())
    return f"---\n{frontmatter}\n---\n\n## 스크립트\n\n{script.script_text or '스크립트 수집 전'}\n\n## 요약 · 콘텐츠 소재\n\n{script.summary}\n\n> {NOTICE}\n"


def generate_scripts(repository: Repository, target_dir: Path) -> list[dict]:
    scripts_dir = Path(target_dir) / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    scripts_by_url = {script.content_url: script for script in repository.list_scripts()}
    entries: list[dict] = []
    desired: set[Path] = set()
    for hospital in repository.list_hospitals():
        for content in repository.list_contents(hospital.hospital_id):
            script = scripts_by_url.get(content.url)
            if script is None or content.relevance_status != "relevant":
                continue
            month = content.published_at.strftime("%Y-%m") if content.published_at else "undated"
            day = content.published_at.strftime("%Y%m%d") if content.published_at else "undated"
            digest = hashlib.sha1(content.url.encode("utf-8")).hexdigest()[:8]
            relative = Path(_hospital_folder(hospital.hospital_id)) / month / f"{day}_{_slug(content.platform)}_{digest}.md"
            path = scripts_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_file_content(hospital, content, script), encoding="utf-8")
            desired.add(path.resolve())
            entries.append({
                "content_url": content.url,
                "hospital_id": hospital.hospital_id,
                "hospital_name": hospital.hospital_name,
                "platform": content.platform,
                "title": content.title,
                "published_at": content.published_at.isoformat() if content.published_at else "",
                "product": content.matched_product or "",
                "usage_status": script.usage_status,
                "path": relative.as_posix(),
                "script_length": len(script.script_text),
                "has_summary": bool(script.summary.strip()),
            })
    for existing in scripts_dir.rglob("*.md"):
        if existing.resolve() not in desired:
            existing.unlink()
    for folder in sorted((path for path in scripts_dir.rglob("*") if path.is_dir()), key=lambda item: len(item.parts), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()
    index = {"scripts": entries}
    (scripts_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entries
