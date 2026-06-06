from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class TxMarketProvider:
    name = "tx-market"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 120.0, "USD", self.name, datetime(2026, 6, 5), "delayed")


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=TxMarketProvider(),
    )


def render_text(renderable) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_tx_buy_creates_position_and_transaction(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    result = router.route("/tx add buy AAPL 10 100")

    assert result.status == "ready"
    position = router.portfolio.list()[0]
    transactions = router.transactions.list()
    assert position["symbol"] == "AAPL"
    assert position["quantity"] == 10
    assert position["average_price"] == 100
    assert transactions[0]["action"] == "buy"


def test_tx_sell_reduces_position_and_records_realized_pnl(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    router.route("/tx add buy AAPL 10 100")

    result = router.route("/tx add sell AAPL 4 120")

    assert result.status == "ready"
    position = router.portfolio.list()[0]
    sell_tx = router.transactions.list()[0]
    assert position["quantity"] == 6
    assert position["average_price"] == 100
    assert sell_tx["action"] == "sell"
    assert sell_tx["realized_pnl"] == 80


def test_tx_list_command_outputs_transactions(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    router.route("/tx add buy AAPL 10 100")

    result = router.route("/tx list")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "AAPL" in output
    assert "buy" in output


def test_portfolio_performance_outputs_realized_and_unrealized_pnl(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    router.route("/tx add buy AAPL 10 100")
    router.route("/tx add sell AAPL 4 120")

    result = router.route("/portfolio performance")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "Realized PnL" in output
    assert "Unrealized PnL" in output
    assert "80.0000" in output
    assert "120.0000" in output
