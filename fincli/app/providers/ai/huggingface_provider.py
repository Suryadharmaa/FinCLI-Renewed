"""HuggingFace provider compatibility wrapper."""

from __future__ import annotations

import os

from fincli.app.providers.ai.http_provider import OpenAICompatibleProvider


class HuggingFaceProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None = None) -> None:
        super().__init__("huggingface", "https://router.huggingface.co/v1", api_key or os.getenv("HUGGINGFACE_API_KEY"))
