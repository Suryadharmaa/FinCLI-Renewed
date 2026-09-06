from __future__ import annotations

import json
from pathlib import Path

from fincli.app.web.security import command_requires_confirmation

TEST_TOKEN = "desktop-session-test-token"


def test_desktop_api_contract(monkeypatch: object) -> None:
    from fastapi.testclient import TestClient

    from fincli.app.web.api import create_app

    monkeypatch.setenv("FINCLI_DESKTOP", "1")  # type: ignore[attr-defined]
    monkeypatch.setenv("FINCLI_DESKTOP_TOKEN", TEST_TOKEN)  # type: ignore[attr-defined]
    with TestClient(create_app()) as client:
        headers = {"Authorization": f"Bearer {TEST_TOKEN}"}
        status = client.get("/api/status", headers=headers)
        info = client.get("/api/desktop/info", headers=headers)

    assert status.status_code == 200
    assert status.json()["mode"] == "desktop"
    assert status.json()["api_contract"] == "2.0"
    assert info.status_code == 200
    assert info.json()["desktop"] is True
    assert info.json()["capabilities"]["paper_trading"] is True


def test_desktop_tauri_origin_preflight(monkeypatch: object) -> None:
    from fastapi.testclient import TestClient

    from fincli.app.web.api import create_app

    monkeypatch.setenv("FINCLI_DESKTOP", "1")  # type: ignore[attr-defined]
    monkeypatch.setenv("FINCLI_DESKTOP_TOKEN", TEST_TOKEN)  # type: ignore[attr-defined]
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/status",
            headers={
                "Origin": "http://tauri.localhost",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,x-fincli-csrf,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_desktop_sensitive_commands_require_confirmation() -> None:
    assert command_requires_confirmation("/trading kill")
    assert command_requires_confirmation("/security purge")


def test_desktop_shell_files_exist() -> None:
    root = Path(__file__).parents[1] / "desktop"
    assert (root / "package.json").is_file()
    assert (root / "frontend" / "index.html").is_file()
    assert (root / "src-tauri" / "src" / "main.rs").is_file()
    config = json.loads((root / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert config["productName"] == "FinCLI"
    assert config["mainBinaryName"] == "fincli"
    assert config["bundle"]["targets"] == ["nsis"]
    assert config["build"]["frontendDist"] == "../../fincli/app/web/static"
    assert "externalBin" not in config["bundle"]
    rust = (root / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    assert 'include_bytes!(env!("FINCLI_BACKEND_PATH"))' in rust
    assert "tauri_plugin_shell" not in rust
    app_js = (root.parent / "fincli" / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "desktopBase" in app_js


def test_desktop_frontend_uses_internal_session() -> None:
    source = (Path(__file__).parents[1] / "fincli" / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    bootstrap = (Path(__file__).parents[1] / "desktop" / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'invoke("desktop_session")' in source
    assert "if(!desktop)localStorage.fincliToken=token" in source
    assert 'invoke("desktop_restart")' in bootstrap


def test_desktop_workspace_assets_and_capabilities(monkeypatch: object) -> None:
    from fastapi.testclient import TestClient

    from fincli.app.cli.commands import COMMANDS
    from fincli.app.web.api import create_app

    monkeypatch.setenv("FINCLI_DESKTOP", "1")  # type: ignore[attr-defined]
    monkeypatch.setenv("FINCLI_DESKTOP_TOKEN", TEST_TOKEN)  # type: ignore[attr-defined]
    with TestClient(create_app()) as client:
        headers = {"Authorization": f"Bearer {TEST_TOKEN}"}
        page = client.get("/", headers=headers)
        capabilities = client.get("/api/desktop/capabilities", headers=headers)
        overview = client.get("/api/desktop/overview", headers=headers)
        action = client.post(
            "/api/desktop/action",
            headers={**headers, "X-FinCLI-CSRF": "local-web"},
            json={"action": "portfolio.view", "params": {}},
        )

    source = page.text
    assert page.status_code == 200
    assert 'href="app.css"' in source
    assert 'src="app.js"' in source
    assert "assets/" not in source
    assert capabilities.status_code == 200
    payload = capabilities.json()
    assert payload["command_count"] == len(COMMANDS) == 155
    assert len(payload["commands"]) == 155
    assert len({row["name"] for row in payload["commands"]}) == 155
    assert all("desktop_supported" in row and "input_schema" in row for row in payload["commands"])
    assert all(row["desktop_available"] for row in payload["commands"])
    assert any(row["terminal_only_reason"] for row in payload["commands"])
    replacements = {row["name"]: row["replacement_action"] for row in payload["commands"] if row["replacement_action"]}
    assert replacements == {
        "/ai_model": "ai.model",
        "/news_model": "provider.news",
        "/notification add": "notification.add",
    }
    assert overview.status_code == 200
    assert {"market", "portfolio", "watchlist", "provider_trust", "alerts"}.issubset(overview.json())
    assert action.status_code == 200
    assert action.json()["action"] == "portfolio.view"


def test_desktop_tables_and_dialogs_are_contained_and_closeable() -> None:
    static = Path(__file__).parents[1] / "fincli" / "app" / "web" / "static"
    css = (static / "app.css").read_text(encoding="utf-8")
    source = (static / "app.js").read_text(encoding="utf-8")

    assert "overflow-x: hidden" in css
    assert "max-height: min(58vh, 560px)" in css
    assert ".table-wrapper table { width: max-content; min-width: 100%" in css
    assert "data-close-results" in source
    assert "document.querySelectorAll(\"[data-close-modal]\")" in source
    assert "pendingConfirmationResolve" in source


def test_light_theme_uses_complete_semantic_surface_palette() -> None:
    css = (Path(__file__).parents[1] / "fincli" / "app" / "web" / "static" / "app.css").read_text(encoding="utf-8")

    assert "body.light {" in css
    assert "color-scheme: light" in css
    for token in ("--panel-glass", "--composer-bg", "--input-bg", "--palette-bg", "--user-bg", "--close-bg"):
        assert css.count(token) >= 2
    assert "body.light .composer" in css
    assert "body.light .modal-backdrop" in css
    source = (Path(__file__).parents[1] / "fincli" / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "localStorage.fincliTheme" in source


def test_desktop_command_loading_uses_unique_request_lifecycle() -> None:
    source = (Path(__file__).parents[1] / "fincli" / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "requestSequence" in source
    assert "visibleMessages" in source
    assert "replaceLoading(requestId" in source
    assert "renderMessagePanel" in source
    assert "data-working" not in source
    assert "document.getElementById(requestId)" not in source
    assert '$("#working")' not in source
    assert "controller.abort()" in source


def test_secret_desktop_replacement_is_not_history_safe() -> None:
    from fincli.app.web.desktop_actions import ACTION_BY_NAME

    spec = ACTION_BY_NAME["notification.add"]
    assert spec.confirmation_required is True
    assert spec.history_safe is False
    assert {field["name"] for field in spec.fields if field["sensitive"]} == {"secret", "chat_id"}


def test_desktop_action_validation_and_policy(monkeypatch: object) -> None:
    from fastapi.testclient import TestClient

    from fincli.app.web.api import create_app

    monkeypatch.setenv("FINCLI_DESKTOP", "1")  # type: ignore[attr-defined]
    monkeypatch.setenv("FINCLI_DESKTOP_TOKEN", TEST_TOKEN)  # type: ignore[attr-defined]
    with TestClient(create_app()) as client:
        headers = {"Authorization": f"Bearer {TEST_TOKEN}", "X-FinCLI-CSRF": "local-web"}
        missing = client.post("/api/desktop/action", headers=headers, json={"action": "market.quote", "params": {}})
        kill = client.post("/api/desktop/action", headers=headers, json={"action": "trading.kill", "params": {}})
        delete = client.post("/api/desktop/action", headers=headers, json={"action": "journal.delete", "params": {"id": "1"}})

    assert missing.status_code == 422
    assert kill.status_code == 200
    assert kill.json()["status"] == "confirmation_required"
    assert delete.status_code == 200
    assert delete.json()["status"] == "confirmation_required"


def test_desktop_runtime_has_restart_and_log_lifecycle() -> None:
    source = (Path(__file__).parents[1] / "desktop" / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    assert "fn desktop_restart" in source
    assert "default_log_path" in source
    assert "stopping: AtomicBool" in source
    assert "generation: AtomicU64" in source
    assert "state.generation.load(Ordering::SeqCst) != generation" in source
    app_source = (Path(__file__).parents[1] / "fincli" / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'invoke("desktop_restart")' in app_source


def test_desktop_build_requires_embedded_backend_for_release() -> None:
    root = Path(__file__).parents[1]
    build = (root / "desktop" / "src-tauri" / "build.rs").read_text(encoding="utf-8")
    spec = (root / "scripts" / "fincli_backend.spec").read_text(encoding="utf-8")
    assert "FINCLI_BACKEND_BINARY" in build
    assert 'PROFILE").as_deref() == Ok("release")' in build
    assert "name=\"fincli-backend\"" in spec
    assert "collect_submodules(\"keyring.backends\")" in spec


def test_desktop_migrates_non_secret_legacy_data(tmp_path: Path, monkeypatch: object) -> None:
    from fincli.app.storage import config_paths

    legacy = tmp_path / "legacy"
    target = tmp_path / "FinCLI"
    legacy.mkdir()
    (legacy / "config.json").write_text("{\"migrated\": true}", encoding="utf-8")
    (legacy / "secrets.env").write_text("API_KEY=do-not-copy", encoding="utf-8")
    monkeypatch.setattr(config_paths, "LEGACY_APP_DIR", legacy)  # type: ignore[attr-defined]
    monkeypatch.setattr(config_paths, "APP_DIR", target)  # type: ignore[attr-defined]

    assert config_paths.migrate_legacy_data() is True
    assert (target / "config.json").read_text(encoding="utf-8") == "{\"migrated\": true}"
    assert not (target / "secrets.env").exists()
