"""Tests for /history resume and relative_time helper."""

from pathlib import Path
from datetime import datetime, timezone, timedelta

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.session_history import SessionHistoryService, relative_time
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))


# --- relative_time tests ---


def test_relative_time_just_now() -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    assert relative_time(now) == "just now"


def test_relative_time_minutes() -> None:
    ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
    assert relative_time(ts) == "5m ago"


def test_relative_time_hours() -> None:
    ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
    assert relative_time(ts) == "3h ago"


def test_relative_time_yesterday() -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    assert relative_time(ts) == "yesterday"


def test_relative_time_days() -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    assert relative_time(ts) == "10d ago"


def test_relative_time_months() -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
    assert relative_time(ts) == "2mo ago"


def test_relative_time_years() -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(timespec="seconds")
    assert relative_time(ts) == "1y ago"


def test_relative_time_invalid() -> None:
    assert relative_time("not-a-date") == "not-a-date"
    assert relative_time("") == ""


# --- session_history resume tests ---


def test_get_session_summary(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    svc = SessionHistoryService(db)
    sid = svc.start_session()
    svc.record_event(sid, "/config", "ready", "config output")
    svc.record_event(sid, "/market AAPL", "ready", "quote output")

    summary = svc.get_session_summary(sid)
    assert "/config" in summary
    assert "/market AAPL" in summary


def test_get_session_summary_empty(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    svc = SessionHistoryService(db)
    sid = svc.start_session()
    assert svc.get_session_summary(sid) == "(empty)"


def test_resume_session(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    svc = SessionHistoryService(db)
    sid = svc.start_session()
    svc.record_event(sid, "/help", "ready", "help output")
    svc.record_event(sid, "/config", "ready", "config output")

    data = svc.resume_session(sid)
    assert data is not None
    assert data["session"]["id"] == sid
    assert len(data["events"]) == 2
    assert data["events"][0]["command"] == "/help"


def test_resume_session_not_found(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    svc = SessionHistoryService(db)
    assert svc.resume_session("nonexistent") is None


def test_get_last_session(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    svc = SessionHistoryService(db)
    sid1 = svc.start_session("first")
    svc.record_event(sid1, "/help", "ready", "")
    sid2 = svc.start_session("second")
    svc.record_event(sid2, "/config", "ready", "")

    last = svc.get_last_session(sid2)
    assert last is not None
    assert last["id"] == sid1


def test_get_last_session_no_other(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    svc = SessionHistoryService(db)
    sid = svc.start_session()
    assert svc.get_last_session(sid) is None


# --- router /history resume tests ---


def test_history_picker_shows_sessions(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    router.route("/config")
    result = router.route("/history")
    assert result.status == "ready"


def test_history_resume_no_other_session(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    result = router.route("/history resume")
    assert result.status == "ready"
    from rich.console import Console
    import io
    console = Console(file=io.StringIO(), force_terminal=False, width=80)
    console.print(result.renderable)
    output = console.file.getvalue()
    assert "Belum ada session lain" in output


def test_history_resume_by_id(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    # Create a second session manually
    sid2 = router.history.start_session("test session")
    router.history.record_event(sid2, "/help", "ready", "help output")
    router.history.record_event(sid2, "/config", "ready", "config output")

    result = router.route(f"/history resume {sid2}")
    assert result.status == "ready"
    from rich.console import Console
    import io
    console = Console(file=io.StringIO(), force_terminal=False, width=80)
    console.print(result.renderable)
    output = console.file.getvalue()
    assert "Resumed session" in output


def test_history_resume_current_session_error(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    result = router.route(f"/history resume {router.session_id}")
    assert result.status == "error"
    from rich.console import Console
    import io
    console = Console(file=io.StringIO(), force_terminal=False, width=80)
    console.print(result.renderable)
    output = console.file.getvalue()
    assert "Sedang di session ini" in output


def test_history_resume_invalid_id(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    result = router.route("/history resume nonexistent")
    assert result.status == "error"


def test_history_current(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    router.route("/config")
    result = router.route("/history current")
    assert result.status == "ready"


def test_history_show(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    result = router.route(f"/history show {router.session_id}")
    assert result.status == "ready"


def test_history_show_not_found(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    result = router.route("/history show nonexistent")
    assert result.status == "error"


def test_history_save_and_delete(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    save = router.route('/history save "Test session"')
    assert save.status == "ready"

    delete = router.route(f"/history delete {router.session_id}")
    assert delete.status == "ready"
