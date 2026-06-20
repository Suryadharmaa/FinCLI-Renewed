"""Configuration loading and persistence.

Secrets are read from environment variables. Non-secret preferences are stored
in a local JSON config file under ~/.fincli by default.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import difflib
import json
import os
from pathlib import Path
from typing import Any

try:
    from dotenv import dotenv_values, load_dotenv
except ImportError:  # pragma: no cover - dependency exists in normal install
    load_dotenv = None  # type: ignore[assignment]
    dotenv_values = None  # type: ignore[assignment]

from fincli.app.utils.errors import ConfigError
from fincli.app.utils.formatting import mask_secret
from fincli.app.storage.config_paths import APP_DIR, CONFIG_FILE
from fincli.app.storage.secrets import load_local_secrets


# Valid provider names for "did you mean?" suggestions
VALID_AI_PROVIDERS = {"openrouter", "gemini", "anthropic", "openai", "together", "huggingface", "groq"}
VALID_MARKET_PROVIDERS = {"yfinance", "custom", "finnhub", "twelvedata", "alphavantage"}
VALID_THEMES = {"midnight", "ocean", "forest", "solarized", "dracula", "nord", "monokai"}


@dataclass(slots=True)
class FinCLISettings:
    ai_provider: str = "openrouter"
    ai_model: str = "openai/gpt-4o-mini"
    market_provider: str = "yfinance"
    news_provider: str = "yfinance"
    market_provider_priority: list[str] = field(default_factory=lambda: ["yfinance"])
    news_provider_priority: list[str] = field(
        default_factory=lambda: ["yfinance", "google_news_rss", "yahoo_finance_rss", "marketaux", "newsapi", "gnews"]
    )
    timezone: str = "Asia/Jakarta"
    default_currency: str = "USD"
    cache_ttl_seconds: int = 300
    provider_timeout_seconds: float = 12.0
    provider_circuit_breaker_failure_threshold: int = 3
    provider_circuit_breaker_cooldown_seconds: float = 60.0
    theme: str = "midnight"

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
            "alphavantage": mask_secret(os.getenv("ALPHA_VANTAGE_API_KEY")),
            "marketaux": mask_secret(os.getenv("MARKETAUX_API_KEY")),
            "newsapi": mask_secret(os.getenv("NEWSAPI_API_KEY")),
            "gnews": mask_secret(os.getenv("GNEWS_API_KEY")),
            "stocknewsapi": mask_secret(os.getenv("STOCKNEWSAPI_API_KEY")),
            "apitube": mask_secret(os.getenv("APITUBE_API_KEY")),
            "benzinga": mask_secret(os.getenv("BENZINGA_API_KEY")),
            "polygon": mask_secret(os.getenv("POLYGON_API_KEY")),
            "tiingo": mask_secret(os.getenv("TIINGO_API_KEY")),
            "fmp": mask_secret(os.getenv("FMP_API_KEY")),
            "eodhd": mask_secret(os.getenv("EODHD_API_KEY")),
            "custom_news": mask_secret(os.getenv("CUSTOM_NEWS_API_KEY") or os.getenv("NEWS_DATA_API_KEY")),
        }
        return data

    def validate(self) -> list[str]:
        """Validate settings and return list of warnings/errors."""
        warnings: list[str] = []

        # Validate AI provider
        if self.ai_provider not in VALID_AI_PROVIDERS:
            suggestion = _suggest(self.ai_provider, VALID_AI_PROVIDERS)
            msg = f"Unknown AI provider '{self.ai_provider}'"
            if suggestion:
                msg += f". Did you mean '{suggestion}'?"
            warnings.append(msg)

        # Validate market provider
        if self.market_provider not in VALID_MARKET_PROVIDERS:
            suggestion = _suggest(self.market_provider, VALID_MARKET_PROVIDERS)
            msg = f"Unknown market provider '{self.market_provider}'"
            if suggestion:
                msg += f". Did you mean '{suggestion}'?"
            warnings.append(msg)

        # Validate theme
        if self.theme not in VALID_THEMES:
            suggestion = _suggest(self.theme, VALID_THEMES)
            msg = f"Unknown theme '{self.theme}'"
            if suggestion:
                msg += f". Did you mean '{suggestion}'?"
            warnings.append(msg)

        # Validate numeric ranges
        if self.cache_ttl_seconds < 0:
            warnings.append(f"cache_ttl_seconds must be >= 0, got {self.cache_ttl_seconds}")
        if self.provider_timeout_seconds <= 0:
            warnings.append(f"provider_timeout_seconds must be > 0, got {self.provider_timeout_seconds}")
        if self.provider_circuit_breaker_failure_threshold < 1:
            warnings.append(f"circuit_breaker_failure_threshold must be >= 1, got {self.provider_circuit_breaker_failure_threshold}")

        return warnings


class ConfigManager:
    """Load, update, and persist non-secret FinCLI settings."""

    def __init__(self, config_file: Path = CONFIG_FILE) -> None:
        self.config_file = config_file
        self.settings = self.load()

    def load(self) -> FinCLISettings:
        dotenv_loaded_keys: set[str] = set()
        if load_dotenv is not None:
            before_env = dict(os.environ)
            load_dotenv()
            if dotenv_values is not None:
                dotenv_loaded_keys = {
                    key
                    for key, value in dotenv_values().items()
                    if key and value is not None and (key not in before_env or before_env.get(key, "") == "")
                }
        # API keys saved from FinCLI commands should override stale project .env values,
        # while explicit OS/process environment variables remain respected.
        load_local_secrets(override_keys=dotenv_loaded_keys)

        if not self.config_file.exists():
            return FinCLISettings()

        try:
            raw = json.loads(self.config_file.read_text(encoding="utf-8"))
            allowed = FinCLISettings.__dataclass_fields__.keys()
            filtered = {key: value for key, value in raw.items() if key in allowed}
            settings = FinCLISettings(**filtered)

            # Validate and warn about issues
            warnings = settings.validate()
            for warning in warnings:
                print(f"[WARNING] config.json: {warning}")

            return settings
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

    def set_news_provider_priority(self, providers: list[str]) -> None:
        normalized = [provider.strip().lower() for provider in providers if provider.strip()]
        if not normalized:
            normalized = ["yfinance", "google_news_rss", "yahoo_finance_rss"]
        self.settings.news_provider_priority = normalized
        self.settings.news_provider = normalized[0]
        self.save()

    def set_market_provider_priority(self, providers: list[str]) -> None:
        normalized = [provider.strip().lower() for provider in providers if provider.strip()]
        if not normalized:
            normalized = ["yfinance"]
        self.settings.market_provider_priority = normalized
        self.settings.market_provider = normalized[0]
        self.save()


def _suggest(value: str, valid_set: set[str], cutoff: float = 0.6) -> str | None:
    """Find closest match using difflib."""
    matches = difflib.get_close_matches(value.lower(), valid_set, n=1, cutoff=cutoff)
    return matches[0] if matches else None
