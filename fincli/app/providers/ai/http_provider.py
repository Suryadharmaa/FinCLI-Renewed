"""HTTP-based AI providers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from fincli.app.providers.ai.base import AIRequest, AIResponse, AIUsage, BaseAIProvider
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
        self._owns_client = client is None

    def _get_client(self, timeout: float) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_connections=10, max_keepalive_connections=5))
            self._owns_client = True
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _payload(self, request: AIRequest, stream: bool = False) -> dict:
        p: dict = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "temperature": request.temperature,
        }
        if stream:
            p["stream"] = True
        return p

    async def complete(self, request: AIRequest) -> AIResponse:
        if not self.api_key:
            raise ProviderError(
                f"API key untuk provider {self.name} belum diatur.",
                f"Gunakan /ai_model key {self.name} <api_key> atau set environment variable.",
            )

        client = self._get_client(request.timeout_seconds)
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=self._payload(request),
                headers=self._headers(),
            )
            if response.status_code == 429:
                raise RateLimitError(f"Provider {self.name} terkena rate limit.")
            response.raise_for_status()
            data = response.json()
            content = _extract_openai_content(data)
            usage = _extract_openai_usage(data)
            return AIResponse(provider=self.name, model=request.model, content=content, usage=usage)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"AI provider {self.name} timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"AI provider {self.name} gagal: HTTP {exc.response.status_code}.") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"Response AI provider {self.name} tidak valid.") from exc

    async def stream_complete(self, request: AIRequest) -> AsyncIterator[str]:
        """Stream tokens via SSE from OpenAI-compatible API."""
        if not self.api_key:
            raise ProviderError(f"API key untuk provider {self.name} belum diatur.")

        client = self._get_client(httpx.Timeout(request.timeout_seconds, connect=10.0))
        async with client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=self._payload(request, stream=True),
            headers=self._headers(),
        ) as response:
            if response.status_code == 429:
                raise RateLimitError(f"Provider {self.name} terkena rate limit.")
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue


class GeminiProviderHTTP(BaseAIProvider):
    """Minimal Gemini generateContent provider."""

    name = "gemini"

    def __init__(self, api_key: str | None, base_url: str = "https://generativelanguage.googleapis.com/v1beta") -> None:
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self, timeout: float) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_connections=10, max_keepalive_connections=5))
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def complete(self, request: AIRequest) -> AIResponse:
        if not self.api_key:
            raise ProviderError("API key untuk provider gemini belum diatur.", "Gunakan /ai_model key gemini <api_key>.")
        url = f"{self.base_url}/models/{request.model}:generateContent?key={self.api_key}"
        payload = {"contents": [{"parts": [{"text": request.prompt}]}]}
        try:
            client = self._get_client(request.timeout_seconds)
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
        self._client: httpx.AsyncClient | None = None

    def _get_client(self, timeout: float) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_connections=10, max_keepalive_connections=5))
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _payload(self, request: AIRequest, stream: bool = False) -> dict:
        p: dict = {
            "model": request.model,
            "max_tokens": 1200,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if stream:
            p["stream"] = True
        return p

    async def complete(self, request: AIRequest) -> AIResponse:
        if not self.api_key:
            raise ProviderError("API key untuk provider anthropic belum diatur.", "Gunakan /ai_model key anthropic <api_key>.")
        try:
            client = self._get_client(request.timeout_seconds)
            response = await client.post(f"{self.base_url}/messages", json=self._payload(request), headers=self._headers())
            if response.status_code == 429:
                raise RateLimitError("Provider anthropic terkena rate limit.")
            response.raise_for_status()
            data = response.json()
            content = data["content"][0]["text"]
            usage_data = data.get("usage", {})
            usage = AIUsage(
                prompt_tokens=usage_data.get("input_tokens", 0),
                completion_tokens=usage_data.get("output_tokens", 0),
                total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            )
            return AIResponse(provider=self.name, model=request.model, content=str(content), usage=usage)
        except httpx.TimeoutException as exc:
            raise ProviderError("AI provider anthropic timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"AI provider anthropic gagal: HTTP {exc.response.status_code}.") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("Response AI provider anthropic tidak valid.") from exc

    async def stream_complete(self, request: AIRequest) -> AsyncIterator[str]:
        """Stream tokens via SSE from Anthropic API."""
        if not self.api_key:
            raise ProviderError("API key untuk provider anthropic belum diatur.")

        client = self._get_client(httpx.Timeout(request.timeout_seconds, connect=10.0))
        async with client.stream(
            "POST",
            f"{self.base_url}/messages",
            json=self._payload(request, stream=True),
            headers=self._headers(),
        ) as response:
            if response.status_code == 429:
                raise RateLimitError("Provider anthropic terkena rate limit.")
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                try:
                    event = json.loads(data_str)
                    if event.get("type") == "content_block_delta":
                        text = event.get("delta", {}).get("text")
                        if text:
                            yield text
                except (json.JSONDecodeError, KeyError):
                    continue


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


def _extract_openai_usage(data: dict[str, object]) -> AIUsage | None:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    return AIUsage(
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        total_tokens=int(usage.get("total_tokens", 0)),
    )
