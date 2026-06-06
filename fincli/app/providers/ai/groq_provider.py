"""Groq provider compatibility wrapper."""

from __future__ import annotations

import os

from fincli.app.providers.ai.http_provider import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None = None) -> None:
        super().__init__("groq", "https://api.groq.com/openai/v1", api_key or os.getenv("GROQ_API_KEY"))
