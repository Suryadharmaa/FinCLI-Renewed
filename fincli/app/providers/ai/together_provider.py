"""Together AI provider compatibility wrapper."""

from __future__ import annotations

import os

from fincli.app.providers.ai.http_provider import OpenAICompatibleProvider


class TogetherProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None = None) -> None:
        super().__init__("together", "https://api.together.xyz/v1", api_key or os.getenv("TOGETHER_API_KEY"))
