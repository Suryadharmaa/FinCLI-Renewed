from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.algo_engine import BUILTIN_STRATEGIES, StrategyEngine
from fincli.app.modules.broker_adapter import AlpacaPaperAdapter, BrokerAdapterRegistry, IBKRPaperAdapter, TradierSandboxAdapter
from fincli.app.modules.realtime_stream import EquityStreamingAdapter, HyperLiquidWebSocketAdapter, KrakenWebSocketAdapter, StreamManager
from fincli.app.modules.trading import BrokerCatalog, OrderAuditLog, PaperTradingEngine, RealtimeConnectorCatalog, RiskGuard
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class AlgoMarketProvider:
    name = "algo-provider"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 150.0, "USD", self.name, datetime.now(UTC), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        # Enough candles for SMA cross + RSI calculation
        return [
            Candle(datetime(2026, 1, 1), 100 + index * 0.3, 102 + index * 0.3, 99 + index * 0.3, 101 + index * 0.3, 1_000 + index)
            for index in range(140)
        ]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol.upper(), self.name, "USD")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="healthy")


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


# ---------------------------------------------------------------------------
# Risk Guard tests
# ---------------------------------------------------------------------------


def test_risk_guard_blocks_order_when_kill_switch_active(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    engine = PaperTradingEngine(db)
    engine.set_kill_switch(True, "test")

    result = engine.risk_guard.check("buy", "AAPL", 1, "market", price=100.0)

    assert not result.passed
    assert "Kill switch" in result.reason


def test_risk_guard_blocks_oversized_position(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    # Set profile with small equity
    db.execute(
        """INSERT INTO user_profile (id, name, equity, currency, leverage, years_in_investment, gameplay)
           VALUES (1, 'Test', 1000, 'USD', '1:1', 1, 'Scalper')"""
    )
    guard = RiskGuard(db)
    guard.max_position_pct = 0.20  # 20% = $200 max

    # Try to buy $500 worth (5 shares * $100)
    result = guard.check("buy", "AAPL", 5, "market", price=100.0)

    assert not result.passed
    assert "exceeds" in result.reason


def test_risk_guard_blocks_leverage(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    db.execute(
        """INSERT INTO user_profile (id, name, equity, currency, leverage, years_in_investment, gameplay)
           VALUES (1, 'Test', 100, 'USD', '1:1', 1, 'Scalper')"""
    )
    guard = RiskGuard(db)
    guard.max_position_pct = 5.0  # Allow up to 500% so leverage check triggers

    # Try to buy $200 worth with only $100 equity
    result = guard.check("buy", "AAPL", 2, "market", price=100.0)

    assert not result.passed
    assert "exceeds available equity" in result.reason


def test_risk_guard_passes_valid_order(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    db.execute(
        """INSERT INTO user_profile (id, name, equity, currency, leverage, years_in_investment, gameplay)
           VALUES (1, 'Test', 10000, 'USD', '1:1', 1, 'Scalper')"""
    )
    guard = RiskGuard(db)

    result = guard.check("buy", "AAPL", 1, "market", price=150.0)

    assert result.passed
    assert result.reason == "passed"


# ---------------------------------------------------------------------------
# Audit Log tests
# ---------------------------------------------------------------------------


def test_audit_log_records_entries(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    audit = OrderAuditLog(db)

    audit.record("placed", "buy AAPL 1 market", order_id=1)
    audit.record("risk_blocked", "kill switch active")
    entries = audit.list_entries()

    assert len(entries) == 2
    # entries are ordered by id DESC (latest first)
    assert entries[0]["action"] == "risk_blocked"
    assert entries[1]["action"] == "placed"
    assert entries[1]["order_id"] == 1


def test_paper_engine_records_audit_on_order(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    engine = PaperTradingEngine(db)

    engine.place_order("buy", "AAPL", 1, "market", price=150.0)
    entries = engine.audit.list_entries()

    assert len(entries) >= 1
    assert entries[0]["action"] == "placed"


def test_paper_engine_records_audit_on_risk_block(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    engine = PaperTradingEngine(db)
    engine.set_kill_switch(True, "test")

    try:
        engine.place_order("buy", "AAPL", 1, "market", price=150.0)
    except Exception:
        pass

    entries = engine.audit.list_entries()
    assert any(e["action"] == "risk_blocked" for e in entries)


# ---------------------------------------------------------------------------
# Paper Engine enhancements
# ---------------------------------------------------------------------------


def test_paper_engine_cancel_order(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    engine = PaperTradingEngine(db)

    # Insert a queued order directly (limit orders without explicit fill stay queued)
    db.execute(
        "INSERT INTO paper_orders (side, symbol, quantity, order_type, price, notional, status, strategy) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("buy", "AAPL", 1, "limit", 100.0, 100.0, "queued", "manual"),
    )
    rows = db.query("SELECT MAX(id) as id FROM paper_orders")
    order_id = int(rows[0]["id"])

    cancelled = engine.cancel_order(order_id)
    assert cancelled["status"] == "cancelled"


def test_paper_engine_positions_aggregation(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    engine = PaperTradingEngine(db)

    engine.place_order("buy", "AAPL", 10, "market", price=100.0)
    engine.place_order("buy", "AAPL", 5, "market", price=110.0)
    engine.place_order("buy", "BTC-USD", 0.1, "market", price=50000.0)

    positions = engine.get_positions()
    symbols = {p["symbol"] for p in positions}

    assert "AAPL" in symbols
    assert "BTC-USD" in symbols
    aapl = next(p for p in positions if p["symbol"] == "AAPL")
    assert float(aapl["net_quantity"]) == 15.0


def test_paper_engine_daily_pnl(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    engine = PaperTradingEngine(db)

    engine.place_order("buy", "AAPL", 10, "market", price=100.0)
    pnl = engine.daily_pnl()

    assert isinstance(pnl, float)


def test_paper_engine_stop_limit_order(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    engine = PaperTradingEngine(db)

    order = engine.place_order("buy", "AAPL", 1, "stop_limit", price=105.0, stop_price=100.0)

    assert order["order_type"] == "stop_limit"
    assert order["stop_price"] == 100.0


# ---------------------------------------------------------------------------
# Broker Adapter tests
# ---------------------------------------------------------------------------


def test_broker_adapter_registry_activate_and_get() -> None:
    registry = BrokerAdapterRegistry()
    adapter = AlpacaPaperAdapter("test-key", "test-secret")

    registry.activate("Alpaca", adapter)

    assert registry.active_name == "Alpaca"
    assert registry.get_active() is adapter
    assert registry.get("Alpaca") is adapter


def test_broker_adapter_registry_deactivate() -> None:
    registry = BrokerAdapterRegistry()
    registry.activate("Alpaca", AlpacaPaperAdapter("k", "s"))
    registry.deactivate()

    assert registry.active_name == ""
    assert registry.get_active() is None


def test_alpaca_adapter_has_required_methods() -> None:
    adapter = AlpacaPaperAdapter("test-key", "test-secret")
    assert hasattr(adapter, "place_order")
    assert hasattr(adapter, "get_orders")
    assert hasattr(adapter, "cancel_order")
    assert hasattr(adapter, "get_positions")
    assert hasattr(adapter, "get_account")
    assert adapter.name == "Alpaca"
    assert adapter.status == "paper_ready"


def test_tradier_adapter_has_required_methods() -> None:
    adapter = TradierSandboxAdapter("test-token")
    assert hasattr(adapter, "place_order")
    assert hasattr(adapter, "get_orders")
    assert hasattr(adapter, "cancel_order")
    assert hasattr(adapter, "get_positions")
    assert hasattr(adapter, "get_account")
    assert adapter.name == "Tradier"
    assert adapter.status == "sandbox_ready"


def test_ibkr_adapter_raises_setup_instructions() -> None:
    import asyncio

    adapter = IBKRPaperAdapter()
    assert adapter.name == "IBKR"
    assert adapter.status == "gateway_required"

    try:
        asyncio.run(adapter.place_order("buy", "AAPL", 1, "market"))
        assert False, "Should have raised"
    except Exception as exc:
        assert "IB Gateway" in str(exc)


def test_broker_catalog_has_paper_ready_and_sandbox_entries() -> None:
    brokers = BrokerCatalog().all()
    modes = {b.name: b.mode for b in brokers}

    assert modes["Alpaca"] == "paper_ready"
    assert modes["Tradier"] == "sandbox_ready"
    assert modes["IBKR"] == "gateway_required"
    assert len(brokers) >= 16


# ---------------------------------------------------------------------------
# Realtime Stream tests
# ---------------------------------------------------------------------------


def test_kraken_adapter_has_required_interface() -> None:
    adapter = KrakenWebSocketAdapter()
    assert adapter.name == "Kraken WebSocket"
    assert adapter.status == "configurable"
    assert hasattr(adapter, "connect")
    assert hasattr(adapter, "disconnect")
    assert hasattr(adapter, "subscribe_ticker")
    assert hasattr(adapter, "subscribe_trades")
    assert hasattr(adapter, "subscribe_ohlc")
    assert hasattr(adapter, "listen")
    assert not adapter.is_connected


def test_hyperliquid_adapter_has_required_interface() -> None:
    adapter = HyperLiquidWebSocketAdapter()
    assert adapter.name == "HyperLiquid WebSocket"
    assert adapter.status == "configurable"
    assert hasattr(adapter, "connect")
    assert hasattr(adapter, "subscribe_l2_book")
    assert hasattr(adapter, "subscribe_trades")
    assert hasattr(adapter, "subscribe_all_mids")
    assert not adapter.is_connected


def test_equity_adapter_has_required_interface() -> None:
    adapter = EquityStreamingAdapter(market_service=None)
    assert adapter.name == "Equity Quote Feed"
    assert adapter.status == "provider_dependent"
    assert hasattr(adapter, "connect")
    assert hasattr(adapter, "subscribe_quote")
    assert not adapter.is_connected


def test_stream_manager_register_and_list() -> None:
    manager = StreamManager()
    manager.register("kraken", KrakenWebSocketAdapter())
    manager.register("hyperliquid", HyperLiquidWebSocketAdapter())

    streams = manager.list_streams()
    names = {s["name"] for s in streams}

    assert "Kraken WebSocket" in names
    assert "HyperLiquid WebSocket" in names


def test_realtime_connector_catalog_has_configurable_status() -> None:
    connectors = RealtimeConnectorCatalog().all()
    statuses = {c.name: c.status for c in connectors}

    assert statuses["Kraken WebSocket"] == "configurable"
    assert statuses["HyperLiquid WebSocket"] == "configurable"


# ---------------------------------------------------------------------------
# Algo Engine tests
# ---------------------------------------------------------------------------


def test_strategy_engine_lists_builtin_strategies() -> None:
    names = {s.name for s in BUILTIN_STRATEGIES}

    assert "sma_cross" in names
    assert "rsi_reversion" in names
    assert "momentum" in names


def test_strategy_engine_runs_sma_cross(tmp_path: Path) -> None:
    import asyncio

    provider = AlgoMarketProvider()
    from fincli.app.services.market_data import MarketDataService

    service = MarketDataService([provider])
    engine = StrategyEngine(service)

    result = asyncio.run(engine.run("sma_cross", "AAPL", "1d"))

    assert result.strategy == "sma_cross"
    assert result.symbol == "AAPL"
    assert result.signal in {"buy", "sell", "hold"}
    assert isinstance(result.confidence, int)


def test_strategy_engine_runs_momentum(tmp_path: Path) -> None:
    import asyncio

    provider = AlgoMarketProvider()
    from fincli.app.services.market_data import MarketDataService

    service = MarketDataService([provider])
    engine = StrategyEngine(service)

    result = asyncio.run(engine.run("momentum", "AAPL", "1d"))

    assert result.strategy == "momentum"
    assert result.signal in {"buy", "sell", "hold"}


# ---------------------------------------------------------------------------
# Router integration tests
# ---------------------------------------------------------------------------


def test_trading_overview_shows_risk_guard_and_audit(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    output = render_text(router.route("/trading").renderable)

    assert "Risk Guard" in output
    assert "Audit Log" in output
    assert "v1.0.0" in output


def test_trading_kill_and_resume(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    kill_output = render_text(router.route("/trading kill").renderable)
    assert "Kill switch" in kill_output or "ACTIVATED" in kill_output

    resume_output = render_text(router.route("/trading resume").renderable)
    assert "deactivated" in resume_output or "re-enabled" in resume_output


def test_trading_risk_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    output = render_text(router.route("/trading risk").renderable)

    assert "Kill Switch" in output
    assert "Daily PnL" in output
    assert "Max Position" in output


def test_trading_audit_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    # Place an order to generate audit entries
    router.route("/trading paper buy AAPL 1 market 100")

    output = render_text(router.route("/trading audit").renderable)

    assert "Audit" in output


def test_trading_positions_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    router.route("/trading paper buy AAPL 10 market 150")
    output = render_text(router.route("/trading positions").renderable)

    assert "AAPL" in output
    assert "Position" in output


def test_trading_cancel_command(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=db)

    # Insert a queued order directly
    db.execute(
        "INSERT INTO paper_orders (side, symbol, quantity, order_type, price, notional, status, strategy) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("buy", "AAPL", 1, "limit", 100.0, 100.0, "queued", "manual"),
    )
    rows = db.query("SELECT MAX(id) as id FROM paper_orders")
    order_id = int(rows[0]["id"]) if rows and rows[0]["id"] else None
    assert order_id is not None

    cancel_output = render_text(router.route(f"/trading cancel {order_id}").renderable)
    assert "cancel" in cancel_output.lower()


def test_trading_algo_list_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    output = render_text(router.route("/trading algo list").renderable)

    assert "sma_cross" in output
    assert "rsi_reversion" in output
    assert "momentum" in output


def test_trading_algo_run_command(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=AlgoMarketProvider(),
    )

    output = render_text(router.route("/trading algo run sma_cross AAPL 1d").renderable)

    assert "sma_cross" in output
    assert "AAPL" in output


def test_trading_stream_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    output = render_text(router.route("/trading stream").renderable)

    assert "Kraken" in output or "Stream" in output


def test_trading_broker_status_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    output = render_text(router.route("/trading broker status").renderable)

    assert "Alpaca" in output
    assert "Tradier" in output
    assert "IBKR" in output


def test_kill_switch_blocks_paper_order(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    router.route("/trading kill")
    result = router.route("/trading paper buy AAPL 1 market 100")

    assert result.status == "error"
    assert "Kill switch" in render_text(result.renderable) or "Risk guard" in render_text(result.renderable).lower()
