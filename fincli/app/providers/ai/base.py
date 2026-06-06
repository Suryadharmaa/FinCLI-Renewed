"""Base AI provider contract for future provider implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AIRequest:
    prompt: str
    model: str
    temperature: float = 0.2
    timeout_seconds: int = 45


@dataclass(frozen=True, slots=True)
class AIResponse:
    provider: str
    model: str
    content: str


class BaseAIProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, request: AIRequest) -> AIResponse:
        """Return a completion response from the provider."""
