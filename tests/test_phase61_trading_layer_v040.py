from __future__ import annotations

import json
from pathlib import Path

import tomllib
from rich.console import Console

import fincli
from fincli.app.cli.commands import CommandRegistry
from fincli.app.cli.router import CommandRouter
from fincli.app.modules.trading import BrokerCatalog, PaperTradingEngine, RealtimeConnectorCatalog
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_realtime_connector_catalog_includes_crypto_websocket_and_equity_feeds() -> None:
    connectors = RealtimeConnectorCatalog().all()
    names = {connector.name for connector in connectors}

    assert {"Kraken WebSocket", "HyperLiquid WebSocket", "Equity Quote Feed"}.issubset(names)
    assert any("crypto" in connector.asset_classes for connector in connectors)
    assert any("equity" in connector.asset_classes for connector in connectors)


def test_broker_catalog_contains_requested_16_integrations() -> None:
    brokers = BrokerCatalog().all()
    names = {broker.name for broker in brokers}

    assert len(brokers) >= 16
    assert {
        "Zerodha",
        "Angel One",
        "Upstox",
        "Fyers",
        "Dhan",
        "Groww",
        "Kotak",
        "IIFL",
        "5paisa",
        "AliceBlue",
        "Shoonya",
        "Motilal",
        "IBKR",
        "Alpaca",
        "Tradier",
        "Saxo",
    }.issubset(names)
    assert all(broker.mode in {"catalog", "paper_ready", "sandbox_ready", "gateway_required", "adapter_stub"} for broker in brokers)


def test_paper_trading_engine_records_orders_locally(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    engine = PaperTradingEngine(db)

    order = engine.place_order("buy", "AAPL", 2, "market", price=185.5, strategy="manual")
    orders = engine.list_orders()

    assert order["side"] == "buy"
    assert order["symbol"] == "AAPL"
    assert order["status"] == "filled"
    assert orders[0]["symbol"] == "AAPL"
    assert orders[0]["notional"] == 371.0


def test_trading_command_routes_without_live_execution(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    overview = render_text(router.route("/trading").renderable)
    brokers = render_text(router.route("/trading brokers").renderable)
    realtime = render_text(router.route("/trading realtime").renderable)
    paper = router.route("/trading paper buy AAPL 1 market 100")
    orders = render_text(router.route("/trading paper orders").renderable)
    risk = render_text(router.route("/trading risk").renderable)
    positions = render_text(router.route("/trading positions").renderable)
    algo_list = render_text(router.route("/trading algo list").renderable)
    audit = render_text(router.route("/trading audit").renderable)
    command_names = {command.name for command in CommandRegistry().all()}

    assert "/trading" in command_names
    assert "Paper Trading" in overview
    assert "Risk Guard" in overview
    assert "Zerodha" in brokers
    assert "Kraken WebSocket" in realtime
    assert paper.status == "ready"
    assert "AAPL" in orders
    assert "Kill Switch" in risk
    assert "Deprecated" in algo_list or "algo" in algo_list.lower()
    assert "Audit" in audit or "audit" in audit.lower()
    assert "Position" in positions


def test_version_bumped_to_040() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads(Path("package.json").read_text(encoding="utf-8"))

    assert fincli.__version__ == "1.6.0"
    assert pyproject["project"]["version"] == "1.6.0"
    assert package["version"] == "1.6.0"
