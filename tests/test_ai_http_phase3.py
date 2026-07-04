import asyncio

import httpx
import pytest

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest
from fincli.app.providers.ai.http_provider import OpenAICompatibleProvider
from fincli.app.providers.ai.manager import AIProviderManager
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import ProviderError


def test_openai_compatible_provider_parses_chat_completion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.url.path == "/v1/chat/completions"
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "Market Summary: response from provider",
                    }
                }
            ]
        }
        return httpx.Response(200, json=payload)

    provider = OpenAICompatibleProvider(
        name="openai",
        base_url="https://api.openai.test/v1",
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.openai.test"),
    )

    response = asyncio.run(provider.complete(AIRequest(prompt="hello", model="gpt-test")))

    assert response.provider == "openai"
    assert response.model == "gpt-test"
    assert "Market Summary" in response.content


def test_openai_compatible_provider_rejects_missing_api_key() -> None:
    provider = OpenAICompatibleProvider(name="openai", base_url="https://api.openai.test/v1", api_key="")

    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.complete(AIRequest(prompt="hello", model="gpt-test")))

    assert "API key" in str(error.value)


def test_ai_provider_manager_creates_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    provider = AIProviderManager().create("openai")

    assert provider.name == "openai"


def test_ai_model_command_updates_runtime_provider(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/ai_model openai gpt-test")

    assert result.status == "ready"
    assert router.ai_provider.name == "openai"
