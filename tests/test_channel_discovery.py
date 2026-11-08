from datetime import date

import pytest

from hospital_marketing.channel_discovery import (
    ChannelCandidate, ChannelDiscoveryService, parse_candidates, validate_candidate,
)
from hospital_marketing.domain import Hospital
from hospital_marketing.repository import Repository
from hospital_marketing.providers import ProviderRequestError


def test_candidate_url_validation_rejects_wrong_platform_and_non_http_schemes():
    valid = ChannelCandidate("홈페이지", "목업 병원", "https://clinic.example.test", "공식 사이트", 0.9)
    assert validate_candidate(valid) == valid

    with pytest.raises(ValueError, match="도메인"):
        validate_candidate(ChannelCandidate("인스타그램", "가짜", "https://example.test", "근거", 0.8))
    with pytest.raises(ValueError, match="URL"):
        validate_candidate(ChannelCandidate("유튜브", "채널", "javascript:alert(1)", "근거", 0.8))
    with pytest.raises(ValueError, match="https"):
        validate_candidate(ChannelCandidate("홈페이지", "사이트", "http://clinic.example.test", "근거", 0.8))


def test_candidates_are_deduplicated_and_only_approval_registers_channel(tmp_path):
    repository = Repository(tmp_path / "app.db")
    repository.initialize()
    hospital = Hospital("MOCK-001", "목업 병원", "가상권역", date(2026, 1, 1))
    repository.upsert_hospital(hospital)
    service = ChannelDiscoveryService(repository)
    candidate = ChannelCandidate("유튜브", "목업 병원 채널", "https://youtube.com/@mock", "공식 소개", 0.75)

    first = service.save_candidates(hospital.hospital_id, [candidate, candidate])
    assert len(first) == 1
    assert service.list_candidates(hospital.hospital_id)[0].status == "pending"
    assert repository.list_channels(hospital.hospital_id) == []

    service.approve(first[0].id)
    assert len(repository.list_channels(hospital.hospital_id)) == 1
    assert service.list_candidates(hospital.hospital_id)[0].status == "approved"
    repository.close()


def test_invalid_response_is_friendly_and_rejection_never_registers_channel(tmp_path):
    with pytest.raises(ProviderRequestError, match="응답 형식"):
        parse_candidates('{"channels":[{"platform":"인스타그램","channel_name":"가짜","url":"https://not-instagram.test","evidence":"근거","confidence":0.7}]}')

    repository = Repository(tmp_path / "app.db")
    repository.initialize()
    hospital = Hospital("MOCK-002", "목업 병원 2", "가상권역")
    repository.upsert_hospital(hospital)
    service = ChannelDiscoveryService(repository)
    candidate = service.save_candidates(hospital.hospital_id, [
        ChannelCandidate("유튜브", "목업 채널", "https://youtu.be/mock", "가상 근거", 0.5)
    ])[0]
    service.reject(candidate.id)
    assert service.list_candidates(hospital.hospital_id)[0].status == "rejected"
    assert repository.list_channels(hospital.hospital_id) == []
    repository.close()
