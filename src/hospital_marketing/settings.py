from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .documents import SUPPORTED_EXTENSIONS


DEFAULT_PRODUCTS = ("울트라클리어", "리뉴비온", "피아모")


@dataclass(frozen=True)
class ProductKeyword:
    term: str
    enabled: bool = True


@dataclass(frozen=True)
class AppSettings:
    source_dir: Path | None = None
    target_dir: Path | None = None
    provider_id: str = "local-cli"
    model_id: str = "claude"
    mock_mode: bool = False
    auto_collect_hospital_channels: bool = True
    enabled_extensions: tuple[str, ...] = SUPPORTED_EXTENSIONS
    product_keywords: tuple[ProductKeyword, ...] = tuple(ProductKeyword(term) for term in DEFAULT_PRODUCTS)
    last_connection_check: dict[str, str | bool] | None = None


def default_settings_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "hospital-marketing-mvp" / "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_settings_path()

    def load(self) -> AppSettings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return AppSettings()
            raw_extensions = data.get("enabled_extensions", SUPPORTED_EXTENSIONS)
            if not isinstance(raw_extensions, (list, tuple)):
                raw_extensions = SUPPORTED_EXTENSIONS
            extensions: list[str] = []
            for value in raw_extensions:
                if not isinstance(value, str):
                    continue
                extension = value.strip().lower()
                if extension and not extension.startswith("."):
                    extension = f".{extension}"
                if extension in SUPPORTED_EXTENSIONS and extension not in extensions:
                    extensions.append(extension)
            raw_keywords = data.get("product_keywords")
            if raw_keywords is None:
                product_keywords = AppSettings().product_keywords
            elif isinstance(raw_keywords, (list, tuple)):
                product_keywords_list: list[ProductKeyword] = []
                seen_keywords: set[str] = set()
                for item in raw_keywords:
                    if not isinstance(item, dict) or not isinstance(item.get("term"), str):
                        continue
                    term = item["term"].strip()
                    if not term or not isinstance(item.get("enabled", True), bool):
                        continue
                    key = " ".join(term.split()).casefold()
                    if key in seen_keywords:
                        continue
                    seen_keywords.add(key)
                    product_keywords_list.append(ProductKeyword(term, item.get("enabled", True)))
                product_keywords = tuple(product_keywords_list)
            else:
                product_keywords = AppSettings().product_keywords
            raw_check = data.get("last_connection_check")
            last_connection_check = None
            if isinstance(raw_check, dict):
                check_provider = raw_check.get("provider_id")
                check_model = raw_check.get("model_id")
                check_succeeded = raw_check.get("succeeded")
                checked_at = raw_check.get("checked_at")
                if (
                    isinstance(check_provider, str)
                    and isinstance(check_model, str)
                    and isinstance(check_succeeded, bool)
                    and isinstance(checked_at, str)
                ):
                    last_connection_check = {
                        "provider_id": check_provider,
                        "model_id": check_model,
                        "succeeded": check_succeeded,
                        "checked_at": checked_at,
                    }
            return AppSettings(
                source_dir=Path(data["source_dir"]) if data.get("source_dir") else None,
                target_dir=Path(data["target_dir"]) if data.get("target_dir") else None,
                provider_id=str(data.get("provider_id") or "mock"),
                model_id=str(data.get("model_id") or ""),
                mock_mode=bool(data.get("mock_mode", True)),
                auto_collect_hospital_channels=bool(data.get("auto_collect_hospital_channels", True)),
                enabled_extensions=tuple(extensions),
                product_keywords=product_keywords,
                last_connection_check=last_connection_check,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(settings)
        data["source_dir"] = str(settings.source_dir) if settings.source_dir else None
        data["target_dir"] = str(settings.target_dir) if settings.target_dir else None
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
