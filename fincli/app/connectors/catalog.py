"""Connector catalog for FinCLI provider roadmap."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Connector:
    name: str
    category: str
    access: str
    coverage: str


class ConnectorCatalog:
    def __init__(self, connectors: tuple[Connector, ...] | None = None) -> None:
        self._connectors = connectors or CONNECTORS

    def all(self) -> tuple[Connector, ...]:
        return self._connectors

    def by_category(self, category: str) -> list[Connector]:
        normalized = category.strip().lower()
        return [item for item in self._connectors if item.category == normalized]

    def find(self, query: str) -> list[Connector]:
        normalized = query.strip().lower()
        if not normalized:
            return list(self._connectors)
        return [
            item
            for item in self._connectors
            if normalized in item.name.lower()
            or normalized in item.category.lower()
            or normalized in item.coverage.lower()
        ]


def _c(name: str, category: str, access: str = "api-key/plan-dependent", coverage: str = "") -> Connector:
    return Connector(name=name, category=category, access=access, coverage=coverage or category)


CONNECTORS: tuple[Connector, ...] = (
    _c("Benzinga News API", "news"),
    _c("Alpha Vantage News & Sentiment", "news", "api-key/free-tier", "market news and sentiment"),
    _c("Marketaux", "news", "api-key/free-tier"),
    _c("APITube", "news"),
    _c("Adanos Market Sentiment", "news"),
    _c("Bloomberg Enterprise News", "news", "enterprise"),
    _c("Reuters News API", "news", "enterprise"),
    _c("Dow Jones Newswires", "news", "enterprise"),
    _c("MT Newswires", "news", "enterprise"),
    _c("Aiera", "news", "enterprise", "earnings call transcripts"),
    _c("Stocktwits API", "news"),
    _c("Reddit API", "news", "oauth/api-key", "community sentiment"),
    _c("X Twitter v2 API", "news"),
    _c("Seeking Alpha API", "news"),
    _c("Financial Times API", "news", "enterprise"),
    _c("CNBC API", "news"),
    _c("MarketWatch API", "news"),
    _c("Polymarket API", "news", "public/api-key", "event markets"),
    _c("NewsAPI.org", "news", "api-key/free-tier"),
    _c("GNews API", "news", "api-key/free-tier"),
    _c("Webhose.io Financial Feed", "news"),
    _c("CityFALCON", "news"),
    _c("TipRanks", "research"),
    _c("Alternative Data Connectors", "alternative"),
    _c("Yahoo Finance News Feed", "news", "fallback/free", "Yahoo Finance news"),
    _c("AnaChart", "research"),
    _c("Daloopa", "research"),
    _c("Morningstar API", "research"),
    _c("S&P Global Capital IQ", "research", "enterprise"),
    _c("FactSet Connect", "research", "enterprise"),
    _c("Moody's Analytics", "research", "enterprise"),
    _c("LSEG Refinitiv Workspace", "research", "enterprise"),
    _c("Zacks Investment Research", "research"),
    _c("Estimize", "research"),
    _c("Briefing.com", "research"),
    _c("Fitch Solutions", "research"),
    _c("TradingView Webhooks", "research", "webhook"),
    _c("Finnhub Stock API", "market", "api-key/free-tier"),
    _c("EDGAR SEC API", "research", "free/public", "SEC filings"),
    _c("OpenCorporates", "research"),
    _c("GuruFocus", "research"),
    _c("InsiderArbitrage", "research"),
    _c("WhaleWisdom", "research", "api-key", "13F tracker"),
    _c("SmartInsider", "research"),
    _c("OpenInsider", "research", "free/public"),
    _c("Polygon.io", "market"),
    _c("Yahoo Finance", "market", "fallback/free", "stocks forex crypto indices commodities ETFs"),
    _c("Alpha Vantage Core APIs", "market", "api-key/free-tier"),
    _c("Barchart OnDemand", "market"),
    _c("IEX Cloud", "market"),
    _c("Algoseek", "market"),
    _c("Twelve Data", "market", "api-key/free-tier"),
    _c("Intrinio", "market"),
    _c("EOD Historical Data", "market"),
    _c("Tradier API", "market"),
    _c("Tiingo", "market"),
    _c("Alpaca Market Data", "market"),
    _c("Interactive Brokers API", "market"),
    _c("Financial Modeling Prep", "market", "api-key/free-tier"),
    _c("MarketStack", "market"),
    _c("Xignite", "market"),
    _c("Nasdaq Data Link", "market"),
    _c("OPRA", "market", "licensed", "options"),
    _c("Livevol Cboe", "market"),
    _c("BarChart Commodities", "market"),
    _c("FRED", "macro", "free/public", "US macro"),
    _c("DBnomics", "macro", "free/public", "global macro"),
    _c("IMF", "macro", "free/public", "global macro"),
    _c("World Bank Open Data", "macro", "free/public", "global macro"),
    _c("OECD Data API", "macro", "free/public"),
    _c("Eurostat API", "macro", "free/public"),
    _c("BEA", "macro", "free/public"),
    _c("BLS", "macro", "free/public"),
    _c("Bank of England API", "macro", "free/public"),
    _c("European Central Bank API", "macro", "free/public"),
    _c("AkShare", "macro", "free/open-source", "China market and macro"),
    _c("BPS API Indonesia", "macro", "public/plan-dependent"),
    _c("Bank Indonesia API SEKI", "macro", "public/plan-dependent"),
    _c("Trading Economics API", "macro"),
    _c("Oanda Forex Labs", "macro"),
    _c("CoinGecko API", "crypto", "free/public"),
    _c("CoinMarketCap API", "crypto"),
    _c("Kraken WebSocket API", "crypto", "free/public"),
    _c("Glassnode API", "crypto"),
    _c("CryptoQuant", "crypto"),
    _c("Messari API", "crypto"),
    _c("DefiLlama API", "crypto", "free/public"),
    _c("The Graph Subgraphs", "crypto"),
    _c("Dune Analytics API", "crypto"),
    _c("Binance API", "crypto", "free/public"),
    _c("CoinAPI", "crypto"),
    _c("Kaiko", "crypto"),
    _c("Nansen API", "crypto"),
    _c("Token Terminal", "crypto"),
    _c("Santiment API", "crypto"),
    _c("MarineTraffic API", "alternative"),
    _c("FlightAware Firehose", "alternative"),
    _c("Google Trends API", "alternative"),
    _c("OpenWeatherMap API", "alternative", "api-key/free-tier"),
    _c("LinkUp API", "alternative"),
    _c("Placer.ai API", "alternative"),
    _c("Ursa Space Satellite Data", "alternative"),
    _c("PatentSight API", "alternative"),
)
