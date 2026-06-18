"""Tests for AI streaming and token usage."""

import asyncio

from fincli.app.providers.ai.base import AIRequest, AIResponse, AIUsage, BaseAIProvider


class MockStreamingProvider(BaseAIProvider):
    """Mock provider that yields tokens one by one."""
    name = "mock-stream"

    def __init__(self, tokens: list[str] | None = None):
        self._tokens = tokens or ["Hello", " world", "!"]

    async def complete(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            provider=self.name,
            model=request.model,
            content="".join(self._tokens),
            usage=AIUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
        )

    async def stream_complete(self, request: AIRequest):
        for token in self._tokens:
            yield token


def test_ai_usage_dataclass() -> None:
    usage = AIUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 20
    assert usage.total_tokens == 30


def test_ai_usage_default() -> None:
    usage = AIUsage()
    assert usage.prompt_tokens == 0
    assert usage.total_tokens == 0


def test_ai_response_with_usage() -> None:
    usage = AIUsage(prompt_tokens=5, completion_tokens=10, total_tokens=15)
    resp = AIResponse(provider="test", model="m", content="hi", usage=usage)
    assert resp.usage is not None
    assert resp.usage.total_tokens == 15


def test_ai_response_no_usage() -> None:
    resp = AIResponse(provider="test", model="m", content="hi")
    assert resp.usage is None


def test_ai_request_stream_field() -> None:
    req = AIRequest(prompt="test", model="m", stream=True)
    assert req.stream is True
    req2 = AIRequest(prompt="test", model="m")
    assert req2.stream is False


def test_mock_streaming_provider() -> None:
    async def _run():
        provider = MockStreamingProvider(["a", "b", "c"])
        req = AIRequest(prompt="test", model="m")
        result = await provider.complete(req)
        assert result.content == "abc"
        assert result.usage is not None
        assert result.usage.total_tokens == 13
    asyncio.run(_run())


def test_mock_streaming_yields_tokens() -> None:
    async def _run():
        provider = MockStreamingProvider(["x", "y", "z"])
        req = AIRequest(prompt="test", model="m")
        tokens = []
        async for t in provider.stream_complete(req):
            tokens.append(t)
        return tokens
    tokens = asyncio.run(_run())
    assert tokens == ["x", "y", "z"]


def test_base_provider_stream_fallback() -> None:
    """Default stream_complete falls back to complete()."""
    class FallbackProvider(BaseAIProvider):
        name = "fallback"

        async def complete(self, request: AIRequest) -> AIResponse:
            return AIResponse(provider="fallback", model="m", content="fallback content")

    async def _run():
        provider = FallbackProvider()
        req = AIRequest(prompt="test", model="m")
        tokens = []
        async for t in provider.stream_complete(req):
            tokens.append(t)
        return tokens
    tokens = asyncio.run(_run())
    assert tokens == ["fallback content"]
