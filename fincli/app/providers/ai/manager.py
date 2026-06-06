"""AI provider catalog and selection state."""

from __future__ import annotations

from dataclasses import dataclass
import os

from fincli.app.providers.ai.base import BaseAIProvider
from fincli.app.providers.ai.http_provider import AnthropicProviderHTTP, GeminiProviderHTTP, OpenAICompatibleProvider


@dataclass(frozen=True, slots=True)
class AIProviderInfo:
    name: str
    env_key: str
    default_model: str
    status: str = "configured"


AI_PROVIDERS: dict[str, AIProviderInfo] = {
    "openrouter": AIProviderInfo("openrouter", "OPENROUTER_API_KEY", "openai/gpt-4o-mini"),
    "gemini": AIProviderInfo("gemini", "GEMINI_API_KEY", "gemini-1.5-flash"),
    "anthropic": AIProviderInfo("anthropic", "ANTHROPIC_API_KEY", "claude-3-5-sonnet-latest"),
    "openai": AIProviderInfo("openai", "OPENAI_API_KEY", "gpt-4o-mini"),
    "together": AIProviderInfo("together", "TOGETHER_API_KEY", "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"),
    "huggingface": AIProviderInfo("huggingface", "HUGGINGFACE_API_KEY", "meta-llama/Llama-3.1-8B-Instruct"),
    "groq": AIProviderInfo("groq", "GROQ_API_KEY", "llama-3.1-70b-versatile"),
}


class AIProviderManager:
    """AI provider catalog and factory."""

    def list_providers(self) -> list[AIProviderInfo]:
        return list(AI_PROVIDERS.values())

    def get(self, name: str) -> AIProviderInfo | None:
        return AI_PROVIDERS.get(name.lower())

    def create(self, name: str) -> BaseAIProvider:
        provider = self.get(name)
        if provider is None:
            raise ValueError(f"AI provider tidak dikenal: {name}")

        api_key = os.getenv(provider.env_key)
        if provider.name == "openrouter":
            return OpenAICompatibleProvider(provider.name, "https://openrouter.ai/api/v1", api_key)
        if provider.name == "openai":
            return OpenAICompatibleProvider(provider.name, "https://api.openai.com/v1", api_key)
        if provider.name == "together":
            return OpenAICompatibleProvider(provider.name, "https://api.together.xyz/v1", api_key)
        if provider.name == "groq":
            return OpenAICompatibleProvider(provider.name, "https://api.groq.com/openai/v1", api_key)
        if provider.name == "huggingface":
            return OpenAICompatibleProvider(provider.name, "https://router.huggingface.co/v1", api_key)
        if provider.name == "gemini":
            return GeminiProviderHTTP(api_key)
        if provider.name == "anthropic":
            return AnthropicProviderHTTP(api_key)
        raise ValueError(f"AI provider tidak didukung: {name}")
