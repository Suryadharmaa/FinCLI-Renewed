"""Base AI provider contract for future provider implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AIUsage:
    """Token usage from an AI completion."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class AIRequest:
    prompt: str
    model: str
    temperature: float = 0.2
    timeout_seconds: int = 45
    stream: bool = False


@dataclass(frozen=True, slots=True)
class AIResponse:
    provider: str
    model: str
    content: str
    usage: AIUsage | None = None


class BaseAIProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, request: AIRequest) -> AIResponse:
        """Return a completion response from the provider."""

    async def stream_complete(self, request: AIRequest) -> AsyncIterator[str]:
        """Yield content tokens via streaming. Default falls back to complete()."""
        response = await self.complete(request)
        yield response.content
