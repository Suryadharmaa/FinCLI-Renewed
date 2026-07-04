from __future__ import annotations

from typing import TYPE_CHECKING

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.economic_calendar import EconomicEvent, calendar_summary, economic_event_rows
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase

if TYPE_CHECKING:
    from pathlib import Path


def test_calendar_summary_and_rows() -> None:
    events = [
        EconomicEvent("Rate Decision", "US", "high", None),
        EconomicEvent("PMI", "US", "medium", None),
    ]

    assert calendar_summary(events)["high"] == 1
    assert economic_event_rows(events)[0]["event"] == "Rate Decision"


def test_calendar_export_uses_fallback_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "empty-secrets.env")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    target = tmp_path / "calendar.csv"

    result = router.route(f"/calendar export csv {target} week")

    assert result.status == "ready"
    assert target.exists()
    assert "Central bank rate decisions" in target.read_text(encoding="utf-8")
