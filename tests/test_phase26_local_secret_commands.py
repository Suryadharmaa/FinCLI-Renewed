from pathlib import Path
import os

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.manager import AIProviderManager
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.secrets import load_local_secrets, read_secrets, save_secret, secret_source


def clear_env(keys: list[str]) -> None:
    for key in keys:
        os.environ.pop(key, None)


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
    )


def test_local_secret_store_saves_and_loads_without_project_env(tmp_path: Path) -> None:
    target = tmp_path / "secrets.env"
    clear_env(["GROQ_API_KEY"])

    save_secret("GROQ_API_KEY", "test-groq-key", path=target)
    os.environ.pop("GROQ_API_KEY", None)
    load_local_secrets(target)

    assert os.getenv("GROQ_API_KEY") == "test-groq-key"
    assert read_secrets(target)["GROQ_API_KEY"] == "test-groq-key"


def test_local_secret_overrides_empty_project_env_value(tmp_path: Path) -> None:
    target = tmp_path / "secrets.env"
    save_secret("GROQ_API_KEY", "persisted-key", path=target)
    os.environ["GROQ_API_KEY"] = ""

    load_local_secrets(target)

    assert os.getenv("GROQ_API_KEY") == "persisted-key"
    assert secret_source("GROQ_API_KEY", target) == "~/.fincli/secrets.env"


def test_local_secret_overrides_stale_project_env_value_when_requested(tmp_path: Path) -> None:
    target = tmp_path / "secrets.env"
    save_secret("FINNHUB_API_KEY", "fresh-global-key", path=target)
    os.environ["FINNHUB_API_KEY"] = "stale-dotenv-key"

    load_local_secrets(target, override=True)

    assert os.getenv("FINNHUB_API_KEY") == "fresh-global-key"
    assert secret_source("FINNHUB_API_KEY", target) == "~/.fincli/secrets.env"


def test_config_manager_load_prefers_saved_local_secret_over_stale_env(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "secrets.env"
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", target)
    clear_env(["FINNHUB_API_KEY"])
    save_secret("FINNHUB_API_KEY", "fresh-global-key", path=target)
    (tmp_path / ".env").write_text('FINNHUB_API_KEY="stale-dotenv-key"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    ConfigManager(tmp_path / "config.json")

    assert os.getenv("FINNHUB_API_KEY") == "fresh-global-key"
    assert secret_source("FINNHUB_API_KEY", target) == "~/.fincli/secrets.env"


def test_ai_model_key_command_persists_key(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "secrets.env"
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", target)
    clear_env(["GROQ_API_KEY"])
    router = make_router(tmp_path)

    result = router.route("/ai_model key groq test-groq-key")

    assert result.status == "ready"
    assert os.getenv("GROQ_API_KEY") == "test-groq-key"
    assert read_secrets(target)["GROQ_API_KEY"] == "test-groq-key"
    assert router.config.settings.ai_provider == "groq"
    assert router.config.settings.ai_model == "llama-3.1-70b-versatile"
    assert "test-groq-key" not in str(result.renderable)


def test_news_model_key_command_persists_market_key_and_base_url(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "secrets.env"
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", target)
    clear_env(["MARKET_DATA_API_KEY", "MARKET_DATA_BASE_URL"])
    router = make_router(tmp_path)

    result = router.route("/news_model key custom market-key https://market.example")

    assert result.status == "ready"
    assert os.getenv("MARKET_DATA_API_KEY") == "market-key"
    assert os.getenv("MARKET_DATA_BASE_URL") == "https://market.example"
    assert router.config.settings.market_provider == "custom"
    assert router.config.settings.news_provider == "custom"
    assert router.config.settings.market_provider_priority[0] == "custom"
    secrets = read_secrets(target)
    assert secrets["MARKET_DATA_API_KEY"] == "market-key"
    assert secrets["MARKET_DATA_BASE_URL"] == "https://market.example"
    assert "market-key" not in str(result.renderable)


def test_ai_provider_reads_key_saved_by_secret_store(tmp_path: Path) -> None:
    target = tmp_path / "secrets.env"
    clear_env(["GROQ_API_KEY"])

    save_secret("GROQ_API_KEY", "test-groq-key", path=target)
    provider = AIProviderManager().create("groq")

    assert provider.api_key == "test-groq-key"
