"""Base news-only provider adapter."""

from fincli.app.providers.market.base import (
    BaseMarketProvider,
    Candle,
    FundamentalSnapshot,
    NewsItem,
    ProviderCapability,
    ProviderStatus,
    Quote,
)
from fincli.app.utils.errors import ProviderError


class NewsProvider(BaseMarketProvider):
    name = "news"

    async def quote(self, symbol: str) -> Quote:
        raise ProviderError("News provider does not support quote.")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        raise ProviderError("News provider does not support OHLCV.")

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        raise ProviderError("News provider not configured to fetch news.", "Use /news_model to select an active market/news provider.")

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        raise ProviderError("News provider does not support fundamentals.")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            realtime=False,
            status="unavailable",
            message="News-only adapter has no active source. Use /news_model for an actual provider.",
        )

    def capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name,
            realtime=False,
            operations=("news",),
            asset_classes=(),
            rate_limit_note="Stub provider; configure via /news_model.",
        )
