"""Anthropic provider compatibility wrapper."""

from __future__ import annotations

import os

from fincli.app.providers.ai.http_provider import AnthropicProviderHTTP


class AnthropicProvider(AnthropicProviderHTTP):
    def __init__(self, api_key: str | None = None) -> None:
        super().__init__(api_key or os.getenv("ANTHROPIC_API_KEY"))
