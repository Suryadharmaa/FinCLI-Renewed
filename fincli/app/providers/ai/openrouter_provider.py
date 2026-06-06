"""OpenRouter provider compatibility wrapper."""

from __future__ import annotations

import os

from fincli.app.providers.ai.http_provider import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None = None) -> None:
        super().__init__("openrouter", "https://openrouter.ai/api/v1", api_key or os.getenv("OPENROUTER_API_KEY"))
