"""Helpers used only by live integration tests."""

import os
from pathlib import Path
from typing import Mapping


def read_gemini_api_key(env_file: Path, environ: Mapping[str, str] | None = None) -> str:
    """Read the process key first, then a KEY=VALUE entry from the test .env."""
    environment = os.environ if environ is None else environ
    process_key = environment.get("GEMINI_API_KEY", "").strip()
    if process_key:
        return process_key
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ""
    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        if key.strip() != "GEMINI_API_KEY":
            continue
        value = value.strip()
        if value[:1] in {"'", '"'}:
            quote = value[0]
            closing_quote = value.find(quote, 1)
            if closing_quote >= 0:
                value = value[1:closing_quote]
        else:
            value = value.split(" #", 1)[0]
        return value.strip()
    return ""
