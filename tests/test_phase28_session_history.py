from pathlib import Path

from fincli.app.cli.router import CommandRouter
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))


def test_history_records_current_session_commands(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    router.route("/config")
    result = router.route("/history")

    assert result.status == "ready"
    assert "Session" in str(result.renderable.title)
    rows = router.history.get_events(router.session_id)
    assert rows[0]["command"] == "/config"
    assert rows[0]["status"] == "ready"


def test_history_save_sessions_show_and_delete(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    router.route("/config")
    save = router.route('/history save "Riset pagi"')
    sessions = router.route("/history sessions")
    show = router.route(f"/history show {router.session_id}")

    assert save.status == "ready"
    assert sessions.status == "ready"
    assert show.status == "ready"
    assert "Riset pagi" in str(show.renderable.title)

    delete = router.route(f"/history delete {router.session_id}")
    assert delete.status == "ready"
    assert router.history.get_events(router.session_id) == []


def test_history_redacts_api_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    router = make_router(tmp_path)

    router.route("/ai_model key groq very-secret-key")

    rows = router.history.get_events(router.session_id)
    assert rows[0]["command"] == "/ai_model key groq <redacted>"
    assert "very-secret-key" not in rows[0]["command"]
