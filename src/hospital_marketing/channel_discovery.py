from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

from .domain import Channel, Hospital
from .providers import ProviderRequestError
from .repository import Repository


PLATFORM_DOMAINS = {
    "네이버 블로그": ("blog.naver.com",),
    "인스타그램": ("instagram.com",),
    "유튜브": ("youtube.com", "youtu.be"),
    "페이스북": ("facebook.com",),
    "카카오톡 채널": ("pf.kakao.com",),
    "틱톡": ("tiktok.com",),
}
PLATFORMS = ("홈페이지", *PLATFORM_DOMAINS)


@dataclass(frozen=True)
class ChannelCandidate:
    platform: str
    channel_name: str
    url: str
    evidence: str
    confidence: float
    id: int = 0
    hospital_id: str = ""
    status: str = "pending"


def validate_candidate(candidate: ChannelCandidate) -> ChannelCandidate:
    if candidate.platform not in PLATFORMS:
        raise ValueError("지원하지 않는 채널입니다")
    parsed = urlsplit(candidate.url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL 형식이 올바르지 않습니다")
    if candidate.platform == "홈페이지":
        if parsed.scheme != "https":
            raise ValueError("홈페이지 URL은 https여야 합니다")
    else:
        host = parsed.hostname.lower().rstrip(".")
        domains = PLATFORM_DOMAINS[candidate.platform]
        if not any(host == domain or host.endswith("." + domain) for domain in domains):
            raise ValueError("채널 플랫폼과 URL 도메인이 일치하지 않습니다")
    if not candidate.channel_name.strip() or not candidate.evidence.strip():
        raise ValueError("채널 이름과 근거가 필요합니다")
    if not 0 <= candidate.confidence <= 1:
        raise ValueError("확신도는 0과 1 사이여야 합니다")
    return ChannelCandidate(candidate.platform, candidate.channel_name.strip(), candidate.url.strip(),
                            candidate.evidence.strip(), candidate.confidence, candidate.id,
                            candidate.hospital_id, candidate.status)


class ChannelDiscoveryService:
    def __init__(self, repository: Repository):
        self.repository = repository

    def save_candidates(self, hospital_id: str, candidates: list[ChannelCandidate]) -> list[ChannelCandidate]:
        saved = []
        for candidate in candidates:
            candidate = validate_candidate(candidate)
            candidate_id = self.repository.save_channel_candidate(
                hospital_id, candidate.platform, candidate.channel_name, candidate.url,
                candidate.evidence, candidate.confidence,
            )
            if candidate_id is not None:
                saved.append(ChannelCandidate(candidate.platform, candidate.channel_name, candidate.url,
                                              candidate.evidence, candidate.confidence, candidate_id,
                                              hospital_id, "pending"))
        return saved

    def list_candidates(self, hospital_id: str, status: str | None = None) -> list[ChannelCandidate]:
        return [ChannelCandidate(row["platform"], row["channel_name"], row["url"], row["evidence"],
                                 row["confidence"], row["id"], row["hospital_id"], row["status"])
                for row in self.repository.list_channel_candidates(hospital_id, status)]

    def approve(self, candidate_id: int) -> None:
        row = self.repository.connection.execute(
            "SELECT * FROM channel_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if row is None or row["status"] != "pending":
            raise ValueError("승인 대기 중인 후보를 찾을 수 없습니다")
        with self.repository.transaction():
            self.repository.add_channel(Channel(row["hospital_id"], row["platform"],
                                                row["channel_name"], row["url"]))
            if not self.repository.set_channel_candidate_status(candidate_id, "approved"):
                raise ValueError("후보 상태가 변경되어 승인할 수 없습니다")

    def reject(self, candidate_id: int) -> None:
        if not self.repository.set_channel_candidate_status(candidate_id, "rejected"):
            raise ValueError("거절할 대기 후보를 찾을 수 없습니다")


def parse_candidates(response: str) -> list[ChannelCandidate]:
    try:
        data = json.loads(response)
        rows = data["channels"]
        if not isinstance(rows, list):
            raise TypeError
        candidates = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError
            candidates.append(validate_candidate(ChannelCandidate(
                str(row["platform"]), str(row["channel_name"]), str(row["url"]),
                str(row["evidence"]), float(row["confidence"]),
            )))
        return candidates
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OverflowError):
        raise ProviderRequestError("채널 검색 응답 형식이 올바르지 않거나 허용되지 않는 URL이 포함되어 있습니다.") from None


def find_hospital_channels(provider: object, hospital: Hospital) -> list[ChannelCandidate]:
    discover = getattr(provider, "discover_channels", None)
    if not callable(discover):
        raise ProviderRequestError("이 제공자는 채널 찾기를 지원하지 않습니다.")
    return parse_candidates(discover(hospital))
