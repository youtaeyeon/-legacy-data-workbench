from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from .domain import Channel, ContentItem, ContentScript, EquipmentDelivery, FieldChange, Hospital, MarketingMaterial


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS hospitals (
    hospital_id TEXT PRIMARY KEY,
    hospital_name TEXT NOT NULL,
    region TEXT,
    contract_date TEXT,
    source_updated_at TEXT
);
CREATE TABLE IF NOT EXISTS hospital_changes (
    id INTEGER PRIMARY KEY,
    hospital_id TEXT NOT NULL REFERENCES hospitals(hospital_id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY,
    hospital_id TEXT NOT NULL REFERENCES hospitals(hospital_id) ON DELETE CASCADE,
    product_name TEXT NOT NULL,
    delivery_date TEXT,
    quantity INTEGER NOT NULL,
    UNIQUE(hospital_id, product_name, delivery_date)
);
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY,
    hospital_id TEXT NOT NULL REFERENCES hospitals(hospital_id) ON DELETE CASCADE,
    product_name TEXT NOT NULL,
    material_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    status TEXT NOT NULL,
    UNIQUE(hospital_id, product_name, material_name)
);
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY,
    hospital_id TEXT NOT NULL REFERENCES hospitals(hospital_id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    url TEXT NOT NULL,
    UNIQUE(hospital_id, platform, url)
);
CREATE TABLE IF NOT EXISTS contents (
    id INTEGER PRIMARY KEY,
    hospital_id TEXT NOT NULL REFERENCES hospitals(hospital_id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT NOT NULL,
    published_at TEXT,
    matched_product TEXT,
    relevance_status TEXT NOT NULL,
    evidence TEXT,
    UNIQUE(hospital_id, platform, url)
);
CREATE TABLE IF NOT EXISTS content_scripts (
    content_url TEXT PRIMARY KEY,
    script_text TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    usage_status TEXT NOT NULL DEFAULT '미활용',
    collected_at TEXT
);
"""


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value is not None else None


def _as_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


class Repository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._connection: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.db_path, isolation_level=None)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()

    def upsert_hospital(self, hospital: Hospital) -> None:
        self.connection.execute(
            """INSERT INTO hospitals (hospital_id, hospital_name, region, contract_date, source_updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(hospital_id) DO UPDATE SET
                 hospital_name=excluded.hospital_name,
                 region=excluded.region,
                 contract_date=excluded.contract_date,
                 source_updated_at=excluded.source_updated_at""",
            (
                hospital.hospital_id,
                hospital.hospital_name,
                hospital.region,
                _iso(hospital.contract_date),
                _iso(hospital.source_updated_at),
            ),
        )

    def get_hospital(self, hospital_id: str) -> Hospital | None:
        row = self.connection.execute(
            "SELECT * FROM hospitals WHERE hospital_id = ?", (hospital_id,)
        ).fetchone()
        if row is None:
            return None
        return Hospital(
            row["hospital_id"],
            row["hospital_name"],
            row["region"],
            _as_date(row["contract_date"]),
            _as_datetime(row["source_updated_at"]),
        )

    def list_hospitals(self) -> list[Hospital]:
        rows = self.connection.execute("SELECT * FROM hospitals ORDER BY hospital_id").fetchall()
        return [
            Hospital(
                row["hospital_id"],
                row["hospital_name"],
                row["region"],
                _as_date(row["contract_date"]),
                _as_datetime(row["source_updated_at"]),
            )
            for row in rows
        ]

    def record_change(self, change: FieldChange) -> None:
        self.connection.execute(
            "INSERT INTO hospital_changes (hospital_id, field_name, old_value, new_value) VALUES (?, ?, ?, ?)",
            (change.hospital_id, change.field_name, change.old_value, change.new_value),
        )

    def list_changes(self, hospital_id: str) -> list[FieldChange]:
        rows = self.connection.execute(
            "SELECT hospital_id, field_name, old_value, new_value FROM hospital_changes WHERE hospital_id=? ORDER BY id",
            (hospital_id,),
        ).fetchall()
        return [FieldChange(row["hospital_id"], row["field_name"], row["old_value"], row["new_value"]) for row in rows]

    def add_delivery(self, delivery: EquipmentDelivery) -> None:
        self.connection.execute(
            """INSERT INTO deliveries (hospital_id, product_name, delivery_date, quantity)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(hospital_id, product_name, delivery_date) DO UPDATE SET quantity=excluded.quantity""",
            (delivery.hospital_id, delivery.product_name, _iso(delivery.delivery_date), delivery.quantity),
        )

    def list_deliveries(self, hospital_id: str) -> list[EquipmentDelivery]:
        rows = self.connection.execute(
            "SELECT * FROM deliveries WHERE hospital_id=? ORDER BY id", (hospital_id,)
        ).fetchall()
        return [EquipmentDelivery(row["hospital_id"], row["product_name"], _as_date(row["delivery_date"]), row["quantity"]) for row in rows]

    def add_material(self, material: MarketingMaterial) -> None:
        self.connection.execute(
            """INSERT INTO materials (hospital_id, product_name, material_name, quantity, status)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(hospital_id, product_name, material_name) DO UPDATE SET
                 quantity=excluded.quantity, status=excluded.status""",
            (material.hospital_id, material.product_name, material.material_name, material.quantity, material.status),
        )

    def list_materials(self, hospital_id: str) -> list[MarketingMaterial]:
        rows = self.connection.execute(
            "SELECT * FROM materials WHERE hospital_id=? ORDER BY id", (hospital_id,)
        ).fetchall()
        return [MarketingMaterial(row["hospital_id"], row["product_name"], row["material_name"], row["quantity"], row["status"]) for row in rows]

    def add_channel(self, channel: Channel) -> None:
        self.connection.execute(
            """INSERT INTO channels (hospital_id, platform, channel_name, url)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(hospital_id, platform, url) DO UPDATE SET channel_name=excluded.channel_name""",
            (channel.hospital_id, channel.platform, channel.channel_name, channel.url),
        )

    def list_channels(self, hospital_id: str) -> list[Channel]:
        rows = self.connection.execute(
            "SELECT * FROM channels WHERE hospital_id=? ORDER BY id", (hospital_id,)
        ).fetchall()
        return [Channel(row["hospital_id"], row["platform"], row["channel_name"], row["url"]) for row in rows]

    def add_content(self, content: ContentItem) -> None:
        self.connection.execute(
            """INSERT INTO contents
               (hospital_id, platform, title, url, description, published_at, matched_product, relevance_status, evidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(hospital_id, platform, url) DO UPDATE SET
                 title=excluded.title, description=excluded.description, published_at=excluded.published_at,
                 matched_product=excluded.matched_product, relevance_status=excluded.relevance_status,
                 evidence=excluded.evidence""",
            (
                content.hospital_id,
                content.platform,
                content.title,
                content.url,
                content.description,
                _iso(content.published_at),
                content.matched_product,
                content.relevance_status,
                content.evidence,
            ),
        )

    def upsert_script(self, script: ContentScript) -> bool:
        old = self.connection.execute("SELECT * FROM content_scripts WHERE content_url=?", (script.content_url,)).fetchone()
        values = (script.script_text, script.summary or (old["summary"] if old else ""), script.usage_status, _iso(script.collected_at))
        columns = ("script_text", "summary", "usage_status", "collected_at")
        if old is not None and tuple(old[key] for key in columns) == values:
            return False
        self.connection.execute(
            """INSERT INTO content_scripts (content_url, script_text, summary, usage_status, collected_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(content_url) DO UPDATE SET script_text=excluded.script_text,
                 summary=excluded.summary, usage_status=excluded.usage_status, collected_at=excluded.collected_at""",
            (script.content_url, *values),
        )
        return old is not None

    def list_scripts(self) -> list[ContentScript]:
        rows = self.connection.execute("SELECT * FROM content_scripts ORDER BY content_url").fetchall()
        return [ContentScript(row["content_url"], row["script_text"], row["summary"], row["usage_status"], _as_date(row["collected_at"])) for row in rows]

    def list_contents(self, hospital_id: str) -> list[ContentItem]:
        rows = self.connection.execute(
            "SELECT * FROM contents WHERE hospital_id=? ORDER BY id", (hospital_id,)
        ).fetchall()
        return [
            ContentItem(
                row["hospital_id"], row["platform"], row["title"], row["url"], row["description"],
                _as_date(row["published_at"]), row["matched_product"], row["relevance_status"], row["evidence"],
            )
            for row in rows
        ]
