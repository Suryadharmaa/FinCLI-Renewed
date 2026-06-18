from __future__ import annotations

from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.alerts import AlertDaemon, AlertService, CONDITIONAL_TYPES, normalize_condition
from fincli.app.modules.exporter import export_all, export_backtest, export_rows
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import CommandError


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


# ---------------------------------------------------------------------------
# Conditional alert tests
# ---------------------------------------------------------------------------


def test_conditional_types_defined() -> None:
    assert "rsi_below" in CONDITIONAL_TYPES
    assert "rsi_above" in CONDITIONAL_TYPES
    assert "volume_above" in CONDITIONAL_TYPES
    assert "macd_cross_up" in CONDITIONAL_TYPES
    assert "macd_cross_down" in CONDITIONAL_TYPES


def test_normalize_condition_accepts_conditional() -> None:
    assert normalize_condition("rsi_below") == "rsi_below"
    assert normalize_condition("RSI_ABOVE") == "rsi_above"
    assert normalize_condition("volume_above") == "volume_above"


def test_normalize_condition_rejects_unknown() -> None:
    try:
        normalize_condition("unknown_condition")
        assert False, "Should have raised"
    except CommandError:
        pass


def test_alert_service_add_conditional(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    service = AlertService(db)

    service.add_conditional("AAPL", "rsi_below", 30, "oversold")
    alerts = service.list()

    assert len(alerts) == 1
    assert alerts[0]["condition"] == "rsi_below"
    assert float(alerts[0]["target"]) == 30


def test_alert_service_history(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    service = AlertService(db)

    service.record_history(1, "AAPL", "above", 200, 205.0, True, "price hit")
    service.record_history(2, "BTC-USD", "below", 50000, 49000.0, True, "price dropped")

    history = service.get_history()
    assert len(history) == 2
    assert history[0].symbol == "BTC-USD"
    assert history[1].symbol == "AAPL"


# ---------------------------------------------------------------------------
# Alert daemon tests
# ---------------------------------------------------------------------------


def test_alert_daemon_initial_state(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    service = AlertService(db)
    daemon = AlertDaemon(service, market_service=None)

    assert not daemon.is_running
    assert daemon.last_check is None
    assert daemon.triggered_count == 0


def test_alert_daemon_check_once_no_market(tmp_path: Path) -> None:
    import asyncio

    db = FinCLIDatabase(tmp_path / "fincli.db")
    service = AlertService(db)
    daemon = AlertDaemon(service, market_service=None)

    results = asyncio.run(daemon.check_once())
    assert results == []  # no market service, no alerts


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


def test_export_rows_csv(tmp_path: Path) -> None:
    rows = [{"symbol": "AAPL", "price": 150}, {"symbol": "BTC-USD", "price": 50000}]
    path = export_rows(rows, "csv", tmp_path / "test.csv")

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "AAPL" in content
    assert "BTC-USD" in content


def test_export_rows_json(tmp_path: Path) -> None:
    rows = [{"symbol": "AAPL", "price": 150}]
    path = export_rows(rows, "json", tmp_path / "test.json")

    assert path.exists()
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["symbol"] == "AAPL"


def test_export_all(tmp_path: Path) -> None:
    portfolio = [{"symbol": "AAPL", "qty": 10}]
    journal = [{"instrument": "AAPL", "bias": "bullish"}]
    alerts = [{"symbol": "AAPL", "condition": "above", "target": 200}]
    trades = [{"side": "buy", "symbol": "AAPL", "qty": 1}]

    written = export_all(tmp_path / "exports", portfolio=portfolio, journal=journal, alerts=alerts, trades=trades, fmt="json")

    assert len(written) == 4
    for path in written:
        assert path.exists()


def test_export_all_partial(tmp_path: Path) -> None:
    written = export_all(tmp_path / "exports", portfolio=[{"a": 1}], fmt="csv")

    assert len(written) == 1
    assert written[0].exists()


# ---------------------------------------------------------------------------
# Router integration tests
# ---------------------------------------------------------------------------


def test_alert_history_command(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=db)

    # Add an alert and trigger it
    router.route("/alert add AAPL above 100")
    router.route("/alert check")

    result = router.route("/alert history")
    output = render_text(result.renderable)

    assert "Alert History" in output


def test_alert_daemon_status_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/alert daemon status")
    output = render_text(result.renderable)

    assert "Status" in output
    assert "stopped" in output


def test_export_all_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    export_dir = tmp_path / "exports"

    result = router.route(f"/export all json {export_dir}")
    output = render_text(result.renderable)

    assert result.status == "ready"
    assert "selesai" in output.lower() or "export" in output.lower()


def test_export_alerts_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    target = tmp_path / "alerts.json"

    result = router.route(f"/export alerts json {target}")
    output = render_text(result.renderable)

    assert result.status == "ready"
