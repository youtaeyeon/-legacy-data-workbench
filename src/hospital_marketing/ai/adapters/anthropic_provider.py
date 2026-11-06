from .base import RemoteAIProvider, SYSTEM_PROMPT


class AnthropicProvider(RemoteAIProvider):
    provider_id = "anthropic"
    endpoint = "https://api.anthropic.com/v1/messages"

    def _post(self, prompt: str):
        return self._client.post(
            self.endpoint,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 1024,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
        )

    def _extract_text(self, payload: dict) -> str:
        blocks = payload["content"]
        return "\n".join(str(block["text"]) for block in blocks if block.get("type") == "text")
