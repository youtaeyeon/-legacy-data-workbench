from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Hospital:
    hospital_id: str
    hospital_name: str
    region: str | None = None
    contract_date: date | None = None
    source_updated_at: datetime | None = None


@dataclass(frozen=True)
class EquipmentDelivery:
    hospital_id: str
    product_name: str
    delivery_date: date | None
    quantity: int


@dataclass(frozen=True)
class MarketingMaterial:
    hospital_id: str
    product_name: str
    material_name: str
    quantity: int
    status: str


@dataclass(frozen=True)
class Channel:
    hospital_id: str
    platform: str
    channel_name: str
    url: str


@dataclass(frozen=True)
class ContentItem:
    hospital_id: str
    platform: str
    title: str
    url: str
    description: str
    published_at: date | None
    matched_product: str | None
    relevance_status: str
    evidence: str | None


@dataclass(frozen=True)
class FieldChange:
    hospital_id: str
    field_name: str
    old_value: str | None
    new_value: str | None
