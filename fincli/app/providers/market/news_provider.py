"""Base news-only provider adapter."""

from fincli.app.providers.market.base import BaseMarketProvider, Candle, FundamentalSnapshot, NewsItem, ProviderCapability, ProviderStatus, Quote
from fincli.app.utils.errors import ProviderError


class NewsProvider(BaseMarketProvider):
    name = "news"

    async def quote(self, symbol: str) -> Quote:
        raise ProviderError("News provider tidak menyediakan quote.")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        raise ProviderError("News provider tidak menyediakan OHLCV.")

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        raise ProviderError("News provider belum dikonfigurasi untuk mengambil berita.", "Gunakan /news_model untuk memilih provider market/news aktif.")

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        raise ProviderError("News provider tidak menyediakan fundamental.")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            realtime=False,
            status="unavailable",
            message="News-only adapter belum memiliki source aktif. Gunakan /news_model untuk provider aktual.",
        )

    def capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name,
            realtime=False,
            operations=("news",),
            asset_classes=(),
            rate_limit_note="Stub provider; configure via /news_model.",
        )
