"""OpenAI provider compatibility wrapper."""

from __future__ import annotations

import os

from fincli.app.providers.ai.http_provider import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None = None) -> None:
        super().__init__("openai", "https://api.openai.com/v1", api_key or os.getenv("OPENAI_API_KEY"))
