from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import ProviderStatus, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase

if TYPE_CHECKING:
    from pathlib import Path


class FakeProvider:
    name = "fake"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol.upper(), price=210.0, currency="USD", provider=self.name, timestamp=datetime(2026, 1, 1), status="test")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, False, "test", "fake")


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=FakeProvider(),
    )


def test_alert_add_list_check_and_remove(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    add_result = router.route("/alert add AAPL above 200 breakout")
    list_result = router.route("/alert")
    check_result = router.route("/alert check")
    rows = router.alerts.list()

    assert add_result.status == "ready"
    assert list_result.status == "ready"
    assert check_result.status == "ready"
    assert rows[0]["active"] == 0

    remove_result = router.route(f"/alert remove {rows[0]['id']}")
    assert remove_result.status == "ready"
    assert router.alerts.list() == []
