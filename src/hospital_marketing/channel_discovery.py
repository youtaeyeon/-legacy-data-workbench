from __future__ import annotations

import json
import re
from datetime import date
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


@dataclass(frozen=True)
class DiscoveredPost:
    platform: str
    title: str
    url: str
    published_at: date | None
    summary: str
    channel_url: str


def parse_discovery_response(response: str) -> tuple[list[ChannelCandidate], list[DiscoveredPost], int]:
    try:
        payload = response.strip()
        fenced_json = re.search(r"```(?:json)?\s*(.*?)\s*(?:```|$)", payload, re.DOTALL | re.IGNORECASE)
        if fenced_json:
            payload = fenced_json.group(1)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            for start, char in enumerate(payload):
                if char == "{":
                    try:
                        data, _ = decoder.raw_decode(payload[start:])
                        break
                    except json.JSONDecodeError:
                        continue
            else:
                raise
        if not isinstance(data, dict):
            raise TypeError
        channels: list[ChannelCandidate] = []
        posts: list[DiscoveredPost] = []
        discarded = 0
        raw_channels = data.get("channels", [])
        raw_posts = data.get("posts", [])
        if not isinstance(raw_channels, list) or not isinstance(raw_posts, list):
            raise TypeError
        for row in raw_channels:
            try:
                if not isinstance(row, dict):
                    raise TypeError
                channels.append(validate_candidate(ChannelCandidate(
                    str(row["platform"]), str(row["channel_name"]), str(row["url"]),
                    str(row["evidence"]), float(row["confidence"]),
                )))
            except (KeyError, TypeError, ValueError, OverflowError):
                discarded += 1
        for row in raw_posts:
            try:
                if not isinstance(row, dict):
                    raise TypeError
                platform = str(row["platform"])
                if platform not in PLATFORM_DOMAINS:
                    raise ValueError
                channel_url = str(row["channel_url"])
                channel = next((item for item in channels if item.url == channel_url and item.platform == platform), None)
                if channel is None:
                    raise ValueError
                parsed = urlsplit(str(row["url"]).strip())
                host = parsed.hostname.lower().rstrip(".") if parsed.hostname else ""
                if parsed.scheme not in {"http", "https"} or not any(
                    host == domain or host.endswith("." + domain) for domain in PLATFORM_DOMAINS[platform]
                ) or parsed.username or parsed.password:
                    raise ValueError
                title, summary = str(row["title"]).strip(), str(row["summary"]).strip()
                if not title or not summary:
                    raise ValueError
                published = date.fromisoformat(str(row["published_at"])) if row.get("published_at") else None
                posts.append(DiscoveredPost(platform, title, parsed.geturl(), published, summary, channel_url))
            except (KeyError, TypeError, ValueError, OverflowError):
                discarded += 1
        return channels, posts[:5], discarded + max(0, len(posts) - 5)
    except (json.JSONDecodeError, TypeError, ValueError):
        raise ProviderRequestError("채널·게시물 검색 응답 형식이 올바르지 않습니다.") from None


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
        payload = response.strip()
        fenced_json = re.search(r"```(?:json)?\s*(.*?)\s*(?:```|$)", payload, re.DOTALL | re.IGNORECASE)
        if fenced_json:
            payload = fenced_json.group(1)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            for start, char in enumerate(payload):
                if char == "{":
                    try:
                        data, _ = decoder.raw_decode(payload[start:])
                        break
                    except json.JSONDecodeError:
                        continue
            else:
                raise
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
