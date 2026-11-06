from collections.abc import Mapping

from .base import RemoteAIProvider, SYSTEM_PROMPT


class OpenAIProvider(RemoteAIProvider):
    provider_id = "openai"
    endpoint = "https://api.openai.com/v1/chat/completions"

    def _post(self, prompt: str):
        return self._client.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
        )

    def _extract_text(self, payload: dict) -> str:
        return str(payload["choices"][0]["message"]["content"])
