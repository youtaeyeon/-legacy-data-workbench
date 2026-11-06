from urllib.parse import quote

from .base import RemoteAIProvider, SYSTEM_PROMPT


class GeminiProvider(RemoteAIProvider):
    provider_id = "gemini"

    def _post(self, prompt: str):
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(self.model, safe='')}:generateContent"
        return self._client.post(
            endpoint,
            headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
            },
        )

    def _extract_text(self, payload: dict) -> str:
        parts = payload["candidates"][0]["content"]["parts"]
        return "\n".join(str(part["text"]) for part in parts if "text" in part)
