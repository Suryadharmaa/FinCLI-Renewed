from __future__ import annotations

import json
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from fincli.app.cli.router import CommandResult
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.web.bridge import execute_command, extract_tables, infer_command, sanitize_web_text, strip_ansi
from fincli.app.web.security import command_requires_confirmation
from fincli.app.web.store import WebStore


class StubRouter:
    def route(self, command: str) -> CommandResult:
        return CommandResult(Panel(f"ran {command}"))


class TableRouter:
    def route(self, command: str) -> CommandResult:
        table = Table(title="Provider Compare: AAPL")
        table.add_column("Provider")
        table.add_column("Price")
        table.add_row("yfinance", "150.00")
        table.add_row("openrouter", "150.00")
        return CommandResult(table)


class ErrorRouter:
    def route(self, command: str) -> CommandResult:
        return CommandResult(Panel("Provider openrouter rate limited.", title="Error"), status="error")


def test_web_config_defaults_and_migrates_old_config(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"theme": "nord"}), encoding="utf-8")
    config = ConfigManager(path)
    assert config.settings.web.host == "127.0.0.1"
    assert config.settings.web.port == 19850
    assert config.settings.web.require_auth is True


def test_web_conversation_persistence(tmp_path: Path) -> None:
    store = WebStore(FinCLIDatabase(tmp_path / "fincli.db"))
    conversation = store.create_conversation("AAPL review", "openrouter", "model")
    store.add_message(conversation["id"], "user", "Analyze AAPL", "/research AAPL")
    loaded = store.get_conversation(conversation["id"])
    assert loaded is not None
    assert loaded["messages"][0]["content"] == "Analyze AAPL"


def test_command_inference_and_sensitive_gate() -> None:
    assert infer_command("Analyze AAPL deeply") == "/research AAPL --deep"
    assert infer_command("Show my portfolio risk") == "/portfolio risk"
    assert command_requires_confirmation("/trading live buy AAPL 1 --confirm")
    result = execute_command(StubRouter(), "/security purge")  # type: ignore[arg-type]
    assert result.status == "confirmation_required"


def test_safe_command_reuses_router() -> None:
    result = execute_command(StubRouter(), "/portfolio")  # type: ignore[arg-type]
    assert result.status == "ready"
    assert "ran /portfolio" in result.content


def test_web_ui_assets_exist() -> None:
    static = Path(__file__).parents[1] / "fincli" / "app" / "web" / "static"
    assert (static / "index.html").is_file()
    assert "Message FinCLI" in (static / "index.html").read_text(encoding="utf-8")


def test_api_health_endpoint() -> None:
    from fastapi.testclient import TestClient

    from fincli.app.web.api import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["version"] == "1.9.0"


TEST_TOKEN = "test-token-abc123"


def _patch_token(monkeypatch: object) -> None:
    """Stub token_matches to accept TEST_TOKEN only."""
    import fincli.app.web.api as api_mod

    def _fake_matches(candidate: str | None) -> bool:
        return bool(candidate) and candidate == TEST_TOKEN

    monkeypatch.setattr(api_mod, "token_matches", _fake_matches)  # type: ignore[arg-type]


def test_auth_correct_token_succeeds(tmp_path: Path, monkeypatch: object) -> None:
    from fastapi.testclient import TestClient

    from fincli.app.web.api import create_app

    _patch_token(monkeypatch)
    with TestClient(create_app()) as client:
        response = client.get("/api/status", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert data["auth"] is True


def test_auth_wrong_token_returns_readable_error(tmp_path: Path, monkeypatch: object) -> None:
    from fastapi.testclient import TestClient

    from fincli.app.web.api import create_app

    _patch_token(monkeypatch)
    with TestClient(create_app()) as client:
        response = client.get("/api/status", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401
    data = response.json()
    assert data["detail"] == "Invalid local access token"
    # Must be a plain string, never [object Object]
    assert isinstance(data["detail"], str)
    assert "[" not in data["detail"]


def test_auth_no_token_returns_401(tmp_path: Path, monkeypatch: object) -> None:
    from fastapi.testclient import TestClient

    from fincli.app.web.api import create_app

    _patch_token(monkeypatch)
    with TestClient(create_app()) as client:
        response = client.get("/api/status")
    assert response.status_code == 401
    data = response.json()
    assert data["detail"] == "Invalid local access token"


def test_auth_whitespace_token_still_works(tmp_path: Path, monkeypatch: object) -> None:
    from fastapi.testclient import TestClient

    from fincli.app.web.api import create_app

    _patch_token(monkeypatch)
    with TestClient(create_app()) as client:
        response = client.get("/api/status", headers={"Authorization": f"Bearer   {TEST_TOKEN}  "})
    assert response.status_code == 200


def test_auth_error_response_is_json_string(tmp_path: Path, monkeypatch: object) -> None:
    """All error responses must have detail as a plain string, never an object."""
    from fastapi.testclient import TestClient

    from fincli.app.web.api import create_app

    _patch_token(monkeypatch)
    with TestClient(create_app()) as client:
        # Wrong token → 401
        r1 = client.get("/api/status", headers={"Authorization": "Bearer bad"})
        assert r1.status_code == 401
        assert isinstance(r1.json()["detail"], str)

        # No CSRF on POST → 403
        r2 = client.post("/api/chat", json={"message": "test"}, headers={"Authorization": f"Bearer {TEST_TOKEN}"})
        assert r2.status_code == 403
        assert isinstance(r2.json()["detail"], str)


# --- Phase 3: ANSI stripping, table extraction, AI status endpoint ---


def test_strip_ansi() -> None:
    assert strip_ansi("\x1b[31merror\x1b[0m") == "error"
    assert strip_ansi("no ansi here") == "no ansi here"
    assert strip_ansi("") == ""
    assert strip_ansi("\x1b[1;32mOK\x1b[0m \x1b[33mwarn\x1b[0m") == "OK warn"


def test_extract_tables_from_rich_table() -> None:
    table = Table(title="Test")
    table.add_column("Name")
    table.add_column("Value")
    table.add_row("AAPL", "150.00")
    table.add_row("MSFT", "300.00")
    tables = extract_tables(table)
    assert len(tables) == 1
    assert tables[0]["columns"] == ["Name", "Value"]
    assert tables[0]["rows"] == [["AAPL", "150.00"], ["MSFT", "300.00"]]


def test_extract_tables_from_panel_returns_empty() -> None:
    tables = extract_tables(Panel("just text"))
    assert tables == []


def test_execute_command_extracts_tables() -> None:
    result = execute_command(TableRouter(), "/provider compare AAPL")  # type: ignore[arg-type]
    assert result.status == "ready"
    assert len(result.tables) == 1
    assert result.tables[0].columns == ["Provider", "Price"]
    assert "yfinance" in result.tables[0].rows[0]


def test_web_rate_limit_is_structured_without_terminal_box() -> None:
    result = execute_command(ErrorRouter(), "/ai test")  # type: ignore[arg-type]
    payload = result.to_dict()
    assert payload["ok"] is False
    assert payload["kind"] == "error"
    assert payload["errors"][0]["title"] == "Openrouter rate limited"
    assert payload["errors"][0]["code"] == "RATE_LIMITED"
    assert payload["errors"][0]["provider"] == "openrouter"
    assert not any(character in json.dumps(payload) for character in "╭╮╯╰─│")


def test_sanitize_web_text_removes_ansi_and_terminal_boxes() -> None:
    raw = "\x1b[31m╭──── Error ────╮\n│ failed │\n╰───────────────╯\x1b[0m"
    clean = sanitize_web_text(raw)
    assert clean == "Error\nfailed"
    assert not any(character in clean for character in "╭╮╯╰─│")


def test_terminal_router_result_remains_rich() -> None:
    result = ErrorRouter().route("/ai test")
    assert isinstance(result.renderable, Panel)


def test_frontend_prefers_structured_components() -> None:
    source = (Path(__file__).parents[1] / "fincli" / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "function errorCard" in source
    assert "function dataTableCard" in source
    assert "function renderResult" in source
    assert "function sanitizeDisplayText" in source
    assert "[object Object]" not in source
    assert "result.errors" in source


def test_structured_css_prevents_page_overflow() -> None:
    source = (Path(__file__).parents[1] / "fincli" / "app" / "web" / "static" / "structured.css").read_text(encoding="utf-8")
    assert "overflow-x:hidden" in source
    assert ".table-wrapper" in source
    assert "overflow-x:auto" in source


def test_web_command_catalog_matches_terminal_registry(monkeypatch: object) -> None:
    from fastapi.testclient import TestClient

    from fincli.app.cli.commands import COMMANDS
    from fincli.app.web.api import create_app

    _patch_token(monkeypatch)
    with TestClient(create_app()) as client:
        response = client.get("/api/commands", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == len(COMMANDS)
    assert {row["name"] for row in payload["commands"]} == {command.name for command in COMMANDS}


def test_every_registered_slash_command_is_forwarded_unchanged() -> None:
    from fincli.app.cli.commands import COMMANDS

    for command in COMMANDS:
        assert infer_command(command.example) == command.example


def test_web_specific_terminal_actions_have_browser_semantics() -> None:
    clear = execute_command(StubRouter(), "/clear")  # type: ignore[arg-type]
    exit_result = execute_command(StubRouter(), "/exit")  # type: ignore[arg-type]
    selector = execute_command(StubRouter(), "/ai_model")  # type: ignore[arg-type]
    assert clear.metadata["action"] == "clear"
    assert exit_result.metadata["action"] == "exit"
    assert selector.metadata["action"] == "open_model_selector"


def test_credential_bearing_command_is_not_saved_or_forwarded() -> None:
    result = execute_command(StubRouter(), "/ai_model key openai secret-value")  # type: ignore[arg-type]
    assert result.ok is False
    assert result.status == "blocked"
    assert result.errors[0].code == "TERMINAL_ONLY_SECRET"


def test_frontend_has_registry_palette_and_sensitive_confirmation() -> None:
    source = (Path(__file__).parents[1] / "fincli" / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'api("/api/commands")' in source
    assert "showCommandPalette" in source
    assert "window.confirm" in source
    assert "confirmation_required" in source


def test_api_ai_status_endpoint(monkeypatch: object) -> None:
    from fastapi.testclient import TestClient

    from fincli.app.web.api import create_app

    _patch_token(monkeypatch)
    with TestClient(create_app()) as client:
        response = client.get("/api/ai/status", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "provider" in data
    assert "model" in data
    assert "display_name" in data
    assert "has_api_key" in data
    assert "available_providers" in data
    assert isinstance(data["available_providers"], list)
    # Should have at least openrouter
    providers = [p["provider"] for p in data["available_providers"]]
    assert "openrouter" in providers


def test_api_ai_reload_endpoint(monkeypatch: object) -> None:
    from fastapi.testclient import TestClient

    from fincli.app.web.api import create_app

    _patch_token(monkeypatch)
    with TestClient(create_app()) as client:
        response = client.post("/api/ai/reload", headers={"Authorization": f"Bearer {TEST_TOKEN}", "X-FinCLI-CSRF": "local-web"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "provider" in data
    assert "model" in data


def test_config_reload_method(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"ai_provider": "openrouter", "ai_model": "gpt-4o"}), encoding="utf-8")
    config = ConfigManager(path)
    assert config.settings.ai_provider == "openrouter"
    assert config.settings.ai_model == "gpt-4o"
    # Modify file
    path.write_text(json.dumps({"ai_provider": "gemini", "ai_model": "gemini-pro"}), encoding="utf-8")
    config.reload()
    assert config.settings.ai_provider == "gemini"
    assert config.settings.ai_model == "gemini-pro"
