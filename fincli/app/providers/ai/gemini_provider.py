"""Gemini provider compatibility wrapper."""

from __future__ import annotations

import os

from fincli.app.providers.ai.http_provider import GeminiProviderHTTP


class GeminiProvider(GeminiProviderHTTP):
    def __init__(self, api_key: str | None = None) -> None:
        super().__init__(api_key or os.getenv("GEMINI_API_KEY"))
