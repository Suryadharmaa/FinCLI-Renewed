"""HTTP-based AI providers."""

from __future__ import annotations

import httpx

from fincli.app.providers.ai.base import AIRequest, AIResponse, BaseAIProvider
from fincli.app.utils.errors import ProviderError, RateLimitError


class OpenAICompatibleProvider(BaseAIProvider):
    """Provider for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self._client = client

    async def complete(self, request: AIRequest) -> AIResponse:
        if not self.api_key:
            raise ProviderError(
                f"API key untuk provider {self.name} belum diatur.",
                f"Gunakan /ai_model key {self.name} <api_key> atau set environment variable.",
            )

        payload = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "temperature": request.temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        close_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=request.timeout_seconds)
        try:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            if response.status_code == 429:
                raise RateLimitError(f"Provider {self.name} terkena rate limit.")
            response.raise_for_status()
            data = response.json()
            content = _extract_openai_content(data)
            return AIResponse(provider=self.name, model=request.model, content=content)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"AI provider {self.name} timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"AI provider {self.name} gagal: HTTP {exc.response.status_code}.") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"Response AI provider {self.name} tidak valid.") from exc
        finally:
            if close_client:
                await client.aclose()


class GeminiProviderHTTP(BaseAIProvider):
    """Minimal Gemini generateContent provider."""

    name = "gemini"

    def __init__(self, api_key: str | None, base_url: str = "https://generativelanguage.googleapis.com/v1beta") -> None:
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")

    async def complete(self, request: AIRequest) -> AIResponse:
        if not self.api_key:
            raise ProviderError("API key untuk provider gemini belum diatur.", "Gunakan /ai_model key gemini <api_key>.")
        url = f"{self.base_url}/models/{request.model}:generateContent?key={self.api_key}"
        payload = {"contents": [{"parts": [{"text": request.prompt}]}]}
        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 429:
                    raise RateLimitError("Provider gemini terkena rate limit.")
                response.raise_for_status()
                data = response.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            return AIResponse(provider=self.name, model=request.model, content=str(content))
        except httpx.TimeoutException as exc:
            raise ProviderError("AI provider gemini timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"AI provider gemini gagal: HTTP {exc.response.status_code}.") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("Response AI provider gemini tidak valid.") from exc


class AnthropicProviderHTTP(BaseAIProvider):
    """Minimal Anthropic Messages API provider."""

    name = "anthropic"

    def __init__(self, api_key: str | None, base_url: str = "https://api.anthropic.com/v1") -> None:
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")

    async def complete(self, request: AIRequest) -> AIResponse:
        if not self.api_key:
            raise ProviderError("API key untuk provider anthropic belum diatur.", "Gunakan /ai_model key anthropic <api_key>.")
        payload = {
            "model": request.model,
            "max_tokens": 1200,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(f"{self.base_url}/messages", json=payload, headers=headers)
                if response.status_code == 429:
                    raise RateLimitError("Provider anthropic terkena rate limit.")
                response.raise_for_status()
                data = response.json()
            content = data["content"][0]["text"]
            return AIResponse(provider=self.name, model=request.model, content=str(content))
        except httpx.TimeoutException as exc:
            raise ProviderError("AI provider anthropic timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"AI provider anthropic gagal: HTTP {exc.response.status_code}.") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("Response AI provider anthropic tidak valid.") from exc


def _extract_openai_content(data: dict[str, object]) -> str:
    choices = data["choices"]
    if not isinstance(choices, list) or not choices:
        raise ValueError("choices kosong")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("choice tidak valid")
    message = first.get("message")
    if isinstance(message, dict) and message.get("content"):
        return str(message["content"])
    text = first.get("text")
    if text:
        return str(text)
    raise ValueError("content kosong")
