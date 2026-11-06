import sqlite3
from datetime import date, datetime

import pytest

from hospital_marketing.domain import Channel, ContentItem, EquipmentDelivery, Hospital, MarketingMaterial
from hospital_marketing.repository import Repository


def _hospital(hospital_id="MOCK-001"):
    return Hospital(
        hospital_id=hospital_id,
        hospital_name=f"목업 병원 {hospital_id}",
        region="가상권역 A",
        contract_date=date(2026, 1, 10),
        source_updated_at=datetime(2026, 1, 10, 9, 0),
    )


def test_hospital_upsert_persists_and_updates_by_id(tmp_path):
    db_path = tmp_path / "data" / "app.db"
    repository = Repository(db_path)
    repository.initialize()
    repository.upsert_hospital(_hospital())
    assert repository.get_hospital("MOCK-001") == _hospital()

    updated = Hospital(
        hospital_id="MOCK-001",
        hospital_name="목업 병원 MOCK-001",
        region="가상권역 B",
        contract_date=date(2026, 1, 10),
        source_updated_at=datetime(2026, 2, 1, 9, 0),
    )
    repository.upsert_hospital(updated)
    repository.close()

    reopened = Repository(db_path)
    reopened.initialize()
    assert reopened.get_hospital("MOCK-001") == updated
    assert len(reopened.list_hospitals()) == 1
    reopened.close()


def test_related_records_are_attached_to_hospital(tmp_path):
    repository = Repository(tmp_path / "app.db")
    repository.initialize()
    repository.upsert_hospital(_hospital())
    delivery = EquipmentDelivery("MOCK-001", "울트라클리어", date(2026, 1, 15), 1)
    material = MarketingMaterial("MOCK-001", "울트라클리어", "제품 소개 리플릿", 10, "준비 완료")
    channel = Channel("MOCK-001", "YouTube", "목업 채널", "https://example.test/channel")

    repository.add_delivery(delivery)
    repository.add_material(material)
    repository.add_channel(channel)

    assert repository.list_deliveries("MOCK-001") == [delivery]
    assert repository.list_materials("MOCK-001") == [material]
    assert repository.list_channels("MOCK-001") == [channel]
    repository.close()


def test_content_records_retain_relevance_and_evidence(tmp_path):
    repository = Repository(tmp_path / "app.db")
    repository.initialize()
    repository.upsert_hospital(_hospital())
    content = ContentItem(
        "MOCK-001", "YouTube", "울트라클리어 소개", "https://example.test/content",
        "목업 설명", date(2026, 3, 1), "울트라클리어", "relevant", "제목에 제품명 포함",
    )

    repository.add_content(content)

    assert repository.list_contents("MOCK-001") == [content]
    repository.close()


def test_foreign_key_rejects_related_record_without_hospital(tmp_path):
    repository = Repository(tmp_path / "app.db")
    repository.initialize()

    with pytest.raises(sqlite3.IntegrityError):
        repository.add_channel(Channel("UNKNOWN", "YouTube", "채널", "https://example.test/channel"))

    repository.close()


def test_transaction_rolls_back_hospital_write(tmp_path):
    repository = Repository(tmp_path / "app.db")
    repository.initialize()

    with pytest.raises(RuntimeError, match="rollback marker"):
        with repository.transaction():
            repository.upsert_hospital(_hospital())
            raise RuntimeError("rollback marker")

    assert repository.get_hospital("MOCK-001") is None
    repository.close()
