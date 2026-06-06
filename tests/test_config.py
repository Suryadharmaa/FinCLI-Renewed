from fincli.app.storage.config import ConfigManager
from fincli.app.utils.formatting import mask_secret


def test_config_save_and_reload(tmp_path) -> None:
    config_file = tmp_path / "config.json"
    manager = ConfigManager(config_file)
    manager.set_ai_model("groq", "llama-3.1-70b-versatile")

    loaded = ConfigManager(config_file)
    assert loaded.settings.ai_provider == "groq"
    assert loaded.settings.ai_model == "llama-3.1-70b-versatile"


def test_mask_secret() -> None:
    assert mask_secret(None) == "not set"
    assert mask_secret("abc") == "set"
    assert mask_secret("sk-1234567890") == "sk-1...7890"
