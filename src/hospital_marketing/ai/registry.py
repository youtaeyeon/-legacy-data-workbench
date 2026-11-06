from collections.abc import Callable, Sequence
from typing import Any

from .adapters.anthropic_provider import AnthropicProvider
from .adapters.gemini_provider import GeminiProvider
from .adapters.openai_provider import OpenAIProvider
from .base import AIProvider
from .mock import MockProvider


class ProviderRegistry:
    def __init__(self, providers: dict[str, Callable[..., AIProvider]] | None = None):
        self._providers = providers or {
            "mock": lambda **_: MockProvider(),
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
            "gemini": GeminiProvider,
        }

    def available(self) -> Sequence[str]:
        return tuple(sorted(self._providers))

    def create(self, provider_id: str, **configuration: Any) -> AIProvider:
        try:
            factory = self._providers[provider_id]
        except KeyError as exc:
            raise ValueError(f"지원하지 않는 AI 제공자: {provider_id}") from exc
        return factory(**configuration)
