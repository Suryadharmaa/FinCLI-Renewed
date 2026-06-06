"""Configuration loading and persistence.

Secrets are read from environment variables. Non-secret preferences are stored
in a local JSON config file under ~/.fincli by default.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency exists in normal install
    load_dotenv = None  # type: ignore[assignment]

from fincli.app.utils.errors import ConfigError
from fincli.app.utils.formatting import mask_secret
from fincli.app.storage.config_paths import APP_DIR, CONFIG_FILE
from fincli.app.storage.secrets import load_local_secrets


@dataclass(slots=True)
class FinCLISettings:
    ai_provider: str = "openrouter"
    ai_model: str = "openai/gpt-4o-mini"
    market_provider: str = "yfinance"
    news_provider: str = "yfinance"
    market_provider_priority: list[str] = field(default_factory=lambda: ["yfinance"])
    timezone: str = "Asia/Jakarta"
    default_currency: str = "USD"
    cache_ttl_seconds: int = 300
    theme: str = "fincli-dark"

    def safe_dict(self) -> dict[str, Any]:
        """Return display-safe config, including masked secret status."""
        data = asdict(self)
        data["api_keys"] = {
            "openrouter": mask_secret(os.getenv("OPENROUTER_API_KEY")),
            "gemini": mask_secret(os.getenv("GEMINI_API_KEY")),
            "anthropic": mask_secret(os.getenv("ANTHROPIC_API_KEY")),
            "openai": mask_secret(os.getenv("OPENAI_API_KEY")),
            "together": mask_secret(os.getenv("TOGETHER_API_KEY")),
            "huggingface": mask_secret(os.getenv("HUGGINGFACE_API_KEY")),
            "groq": mask_secret(os.getenv("GROQ_API_KEY")),
            "market_data": mask_secret(os.getenv("MARKET_DATA_API_KEY")),
            "news_data": mask_secret(os.getenv("NEWS_DATA_API_KEY")),
            "finnhub": mask_secret(os.getenv("FINNHUB_API_KEY")),
            "twelvedata": mask_secret(os.getenv("TWELVE_DATA_API_KEY")),
        }
        return data


class ConfigManager:
    """Load, update, and persist non-secret FinCLI settings."""

    def __init__(self, config_file: Path = CONFIG_FILE) -> None:
        self.config_file = config_file
        self.settings = self.load()

    def load(self) -> FinCLISettings:
        if load_dotenv is not None:
            load_dotenv()
        load_local_secrets()

        if not self.config_file.exists():
            return FinCLISettings()

        try:
            raw = json.loads(self.config_file.read_text(encoding="utf-8"))
            allowed = FinCLISettings.__dataclass_fields__.keys()
            filtered = {key: value for key, value in raw.items() if key in allowed}
            return FinCLISettings(**filtered)
        except Exception as exc:  # noqa: BLE001
            raise ConfigError(
                "Config lokal gagal dibaca.",
                "Periksa ~/.fincli/config.json atau hapus file tersebut untuk memakai default.",
            ) from exc

    def save(self) -> None:
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            self.config_file.write_text(
                json.dumps(asdict(self.settings), indent=2),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            raise ConfigError("Config lokal gagal disimpan.") from exc

    def set_ai_model(self, provider: str, model: str) -> None:
        self.settings.ai_provider = provider.strip().lower()
        self.settings.ai_model = model.strip()
        self.save()

    def set_market_provider(self, provider: str) -> None:
        self.settings.market_provider = provider.strip().lower()
        self.save()

    def set_news_provider(self, provider: str) -> None:
        self.settings.news_provider = provider.strip().lower()
        self.save()

    def set_market_provider_priority(self, providers: list[str]) -> None:
        normalized = [provider.strip().lower() for provider in providers if provider.strip()]
        if not normalized:
            normalized = ["yfinance"]
        self.settings.market_provider_priority = normalized
        self.settings.market_provider = normalized[0]
        self.settings.news_provider = normalized[0]
        self.save()
