"""News connector catalog and lightweight fetch adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import os
import re
from typing import Any
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import httpx

from fincli.app.providers.market.base import NewsItem
from fincli.app.utils.errors import ProviderError


@dataclass(frozen=True, slots=True)
class NewsConnectorSpec:
    slug: str
    name: str
    access: str
    category: str
    env_key: str = ""
    url_template: str = ""
    notes: str = ""


API_KEY_NEWS_CONNECTORS: tuple[NewsConnectorSpec, ...] = (
    NewsConnectorSpec("marketaux", "Marketaux", "free-tier", "market-news", "MARKETAUX_API_KEY"),
    NewsConnectorSpec("newsapi", "NewsAPI.org", "free-tier", "general-news", "NEWSAPI_API_KEY"),
    NewsConnectorSpec("gnews", "GNews", "free-tier", "general-news", "GNEWS_API_KEY"),
    NewsConnectorSpec("alphavantage_news", "Alpha Vantage News Sentiment", "free-tier", "market-news", "ALPHA_VANTAGE_API_KEY"),
    NewsConnectorSpec("finnhub_news", "Finnhub Company News", "free-tier", "market-news", "FINNHUB_API_KEY"),
    NewsConnectorSpec("stocknewsapi", "StockNewsAPI", "free-tier", "market-news", "STOCKNEWSAPI_API_KEY"),
    NewsConnectorSpec("apitube", "APITube", "free-tier", "market-news", "APITUBE_API_KEY"),
    NewsConnectorSpec("benzinga", "Benzinga News", "api-key", "market-news", "BENZINGA_API_KEY"),
    NewsConnectorSpec("polygon_benzinga", "Polygon Benzinga News", "api-key", "market-news", "POLYGON_API_KEY"),
    NewsConnectorSpec("tiingo_news", "Tiingo News", "free-tier", "market-news", "TIINGO_API_KEY"),
    NewsConnectorSpec("fmp_news", "Financial Modeling Prep News", "free-tier", "market-news", "FMP_API_KEY"),
    NewsConnectorSpec("eodhd_news", "EOD Historical Data News", "free-tier", "market-news", "EODHD_API_KEY"),
    NewsConnectorSpec("iex_news", "IEX Cloud News", "api-key", "market-news", "IEX_CLOUD_API_KEY"),
    NewsConnectorSpec("intrinio_news", "Intrinio News", "api-key", "market-news", "INTRINIO_API_KEY"),
    NewsConnectorSpec("twelvedata_news", "Twelve Data News", "api-key", "market-news", "TWELVE_DATA_API_KEY"),
    NewsConnectorSpec("custom_news", "Custom News API", "custom", "custom", "CUSTOM_NEWS_API_KEY"),
)


RSS_SOURCES: tuple[tuple[str, str, str, str], ...] = (
    ("google_news_rss", "Google News RSS", "market-news", "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"),
    ("yahoo_finance_rss", "Yahoo Finance RSS", "market-news", "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"),
    ("marketwatch_rss", "MarketWatch RSS", "market-news", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("cnbc_business_rss", "CNBC Business RSS", "business", "https://www.cnbc.com/id/10001147/device/rss/rss.html"),
    ("cnbc_markets_rss", "CNBC Markets RSS", "market-news", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("ap_business_rss", "AP Business RSS", "business", "https://apnews.com/hub/business?output=rss"),
    ("guardian_business_rss", "Guardian Business RSS", "business", "https://www.theguardian.com/uk/business/rss"),
    ("bbc_business_rss", "BBC Business RSS", "business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("npr_business_rss", "NPR Business RSS", "business", "https://feeds.npr.org/1006/rss.xml"),
    ("abc_business_rss", "ABC Business RSS", "business", "https://abcnews.go.com/abcnews/businessheadlines"),
    ("investing_com_news_rss", "Investing.com News RSS", "market-news", "https://www.investing.com/rss/news.rss"),
    ("investing_com_stock_rss", "Investing.com Stock Market RSS", "equity", "https://www.investing.com/rss/stock.rss"),
    ("investing_com_forex_rss", "Investing.com Forex RSS", "forex", "https://www.investing.com/rss/forex.rss"),
    ("investing_com_commodities_rss", "Investing.com Commodities RSS", "commodities", "https://www.investing.com/rss/commodities.rss"),
    ("investing_com_economy_rss", "Investing.com Economy RSS", "macro", "https://www.investing.com/rss/economic.rss"),
    ("nasdaq_news_rss", "Nasdaq News RSS", "equity", "https://www.nasdaq.com/feed/rssoutbound?category=Stocks"),
    ("seeking_alpha_market_news_rss", "Seeking Alpha Market News RSS", "market-news", "https://seekingalpha.com/market_currents.xml"),
    ("sec_press_rss", "SEC Press Releases RSS", "regulatory", "https://www.sec.gov/news/pressreleases.rss"),
    ("sec_litigation_rss", "SEC Litigation RSS", "regulatory", "https://www.sec.gov/litigation/litreleases.rss"),
    ("fed_press_rss", "Federal Reserve Press RSS", "macro", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("fed_speeches_rss", "Federal Reserve Speeches RSS", "macro", "https://www.federalreserve.gov/feeds/speeches.xml"),
    ("ecb_press_rss", "ECB Press RSS", "macro", "https://www.ecb.europa.eu/rss/press.html"),
    ("imf_news_rss", "IMF News RSS", "macro", "https://www.imf.org/en/News/RSS"),
    ("world_bank_news_rss", "World Bank News RSS", "macro", "https://www.worldbank.org/en/news/all?format=rss"),
    ("oecd_news_rss", "OECD News RSS", "macro", "https://www.oecd.org/newsroom/publicationsdocuments/rss.xml"),
    ("bis_news_rss", "BIS News RSS", "macro", "https://www.bis.org/list/press_releases/index.rss"),
    ("boe_news_rss", "Bank of England News RSS", "macro", "https://www.bankofengland.co.uk/rss/news"),
    ("rba_media_rss", "Reserve Bank of Australia RSS", "macro", "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"),
    ("boc_press_rss", "Bank of Canada Press RSS", "macro", "https://www.bankofcanada.ca/press/feed/"),
    ("boj_news_rss", "Bank of Japan News RSS", "macro", "https://www.boj.or.jp/rss/whatsnew_en.xml"),
    ("bis_speeches_rss", "BIS Speeches RSS", "macro", "https://www.bis.org/list/speeches/index.rss"),
    ("treasury_press_rss", "US Treasury Press RSS", "macro", "https://home.treasury.gov/news/press-releases/rss"),
    ("bea_news_rss", "BEA News RSS", "macro", "https://www.bea.gov/news/rss.xml"),
    ("bls_news_rss", "BLS News RSS", "macro", "https://www.bls.gov/feed/news_release.rss"),
    ("census_news_rss", "US Census News RSS", "macro", "https://www.census.gov/newsroom/press-releases.xml"),
    ("eia_news_rss", "EIA News RSS", "energy", "https://www.eia.gov/rss/todayinenergy.xml"),
    ("ft_markets_rss", "Financial Times Markets RSS", "market-news", "https://www.ft.com/markets?format=rss"),
    ("ft_companies_rss", "Financial Times Companies RSS", "equity", "https://www.ft.com/companies?format=rss"),
    ("ft_global_economy_rss", "Financial Times Global Economy RSS", "macro", "https://www.ft.com/global-economy?format=rss"),
    ("fortune_finance_rss", "Fortune Finance RSS", "business", "https://fortune.com/section/finance/feed/"),
    ("fortune_crypto_rss", "Fortune Crypto RSS", "crypto", "https://fortune.com/crypto/feed/"),
    ("forbes_business_rss", "Forbes Business RSS", "business", "https://www.forbes.com/business/feed/"),
    ("forbes_markets_rss", "Forbes Markets RSS", "market-news", "https://www.forbes.com/markets/feed/"),
    ("business_insider_markets_rss", "Business Insider Markets RSS", "market-news", "https://markets.businessinsider.com/rss/news"),
    ("morningstar_news_rss", "Morningstar News RSS", "equity", "https://www.morningstar.com/rss"),
    ("zacks_rss", "Zacks RSS", "equity", "https://www.zacks.com/rss.xml"),
    ("fool_rss", "Motley Fool RSS", "equity", "https://www.fool.com/feeds/index.aspx"),
    ("finviz_news_rss", "Finviz News RSS", "equity", "https://finviz.com/news.ashx"),
    ("benzinga_fintech_rss", "Benzinga Fintech RSS", "equity", "https://www.benzinga.com/feed"),
    ("stocktwits_trending_rss", "Stocktwits Trending RSS", "sentiment", "https://stocktwits.com/symbol/{symbol}.rss"),
    ("cryptopanic_rss", "CryptoPanic RSS", "crypto", "https://cryptopanic.com/news/rss/"),
    ("coindesk_rss", "CoinDesk RSS", "crypto", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph_rss", "Cointelegraph RSS", "crypto", "https://cointelegraph.com/rss"),
    ("decrypt_rss", "Decrypt RSS", "crypto", "https://decrypt.co/feed"),
    ("theblock_rss", "The Block RSS", "crypto", "https://www.theblock.co/rss.xml"),
    ("bitcoin_magazine_rss", "Bitcoin Magazine RSS", "crypto", "https://bitcoinmagazine.com/.rss/full/"),
    ("fxstreet_news_rss", "FXStreet News RSS", "forex", "https://www.fxstreet.com/rss/news"),
    ("forexlive_rss", "Forexlive RSS", "forex", "https://www.forexlive.com/feed/news"),
    ("dailyfx_rss", "DailyFX RSS", "forex", "https://www.dailyfx.com/feeds/all"),
    ("kitco_news_rss", "Kitco News RSS", "commodities", "https://www.kitco.com/rss/news"),
    ("oilprice_rss", "OilPrice RSS", "commodities", "https://oilprice.com/rss/main"),
    ("mining_com_rss", "Mining.com RSS", "commodities", "https://www.mining.com/feed/"),
    ("agweb_rss", "AgWeb RSS", "commodities", "https://www.agweb.com/rss.xml"),
    ("spglobal_commodity_rss", "S&P Global Commodity Insights RSS", "commodities", "https://www.spglobal.com/commodityinsights/en/rss-feed"),
    ("nikkei_asia_rss", "Nikkei Asia RSS", "asia", "https://asia.nikkei.com/rss/feed/nar"),
    ("scmp_business_rss", "SCMP Business RSS", "asia", "https://www.scmp.com/rss/92/feed"),
    ("japantimes_business_rss", "Japan Times Business RSS", "asia", "https://www.japantimes.co.jp/business/feed/"),
    ("straits_times_business_rss", "Straits Times Business RSS", "asia", "https://www.straitstimes.com/news/business/rss.xml"),
    ("the_edge_markets_rss", "The Edge Markets RSS", "asia", "https://theedgemalaysia.com/rss"),
    ("jakarta_post_business_rss", "Jakarta Post Business RSS", "indonesia", "https://www.thejakartapost.com/feeds/business.xml"),
    ("cna_business_rss", "CNA Business RSS", "asia", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6936"),
    ("korea_herald_business_rss", "Korea Herald Business RSS", "asia", "https://www.koreaherald.com/rss/020000000000.xml"),
    ("taipei_times_business_rss", "Taipei Times Business RSS", "asia", "https://www.taipeitimes.com/xml/index.rss"),
    ("hindustan_business_rss", "Hindustan Times Business RSS", "india", "https://www.hindustantimes.com/feeds/rss/business/rssfeed.xml"),
    ("economic_times_markets_rss", "Economic Times Markets RSS", "india", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("moneycontrol_rss", "Moneycontrol RSS", "india", "https://www.moneycontrol.com/rss/latestnews.xml"),
    ("livemint_markets_rss", "Livemint Markets RSS", "india", "https://www.livemint.com/rss/markets"),
    ("euronews_business_rss", "Euronews Business RSS", "europe", "https://www.euronews.com/rss?level=theme&name=business"),
    ("dw_business_rss", "DW Business RSS", "europe", "https://rss.dw.com/xml/rss-en-bus"),
    ("le_monde_economy_rss", "Le Monde Economy RSS", "europe", "https://www.lemonde.fr/en/economy/rss_full.xml"),
    ("el_pais_economy_rss", "El Pais Economy RSS", "europe", "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada"),
    ("reuters_business_rss", "Reuters Business RSS", "business", "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best"),
    ("reuters_markets_rss", "Reuters Markets RSS", "market-news", "https://www.reutersagency.com/feed/?best-topics=markets&post_type=best"),
    ("aljazeera_economy_rss", "Al Jazeera Economy RSS", "global", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("africa_business_rss", "Africa Business RSS", "global", "https://www.africabusiness.com/feed/"),
    ("bloomberg_market_rss", "Bloomberg Markets RSS", "market-news", "https://feeds.bloomberg.com/markets/news.rss"),
    ("bloomberg_economics_rss", "Bloomberg Economics RSS", "macro", "https://feeds.bloomberg.com/economics/news.rss"),
    ("bloomberg_technology_rss", "Bloomberg Technology RSS", "tech", "https://feeds.bloomberg.com/technology/news.rss"),
    ("wsj_markets_rss", "Wall Street Journal Markets RSS", "market-news", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("wsj_world_news_rss", "Wall Street Journal World RSS", "global", "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
    ("wsj_business_rss", "Wall Street Journal Business RSS", "business", "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml"),
    ("barrons_rss", "Barron's RSS", "market-news", "https://www.barrons.com/xml/rss/3_7510.xml"),
    ("thestreet_rss", "TheStreet RSS", "market-news", "https://www.thestreet.com/.rss/full/"),
    ("marketbeat_rss", "MarketBeat RSS", "equity", "https://www.marketbeat.com/feed/"),
    ("prnewswire_financial_rss", "PR Newswire Financial RSS", "corporate", "https://www.prnewswire.com/rss/news-releases-list.rss"),
    ("globenewswire_rss", "GlobeNewswire RSS", "corporate", "https://www.globenewswire.com/RssFeed/subjectcode/27-Financial%20Services/feedTitle/GlobeNewswire%20-%20Financial%20Services"),
    ("businesswire_financial_rss", "Business Wire RSS", "corporate", "https://www.businesswire.com/portal/site/home/template.PAGE/news/rss/?javax.portlet.tpst=08c2aa13f2fe3d4dc1b6751ae1de75dd&javax.portlet.rst_08c2aa13f2fe3d4dc1b6751ae1de75dd_feedName=Financial"),
    ("accesswire_financial_rss", "ACCESSWIRE RSS", "corporate", "https://www.accesswire.com/rss/financial-services"),
    ("openpr_finance_rss", "OpenPR Finance RSS", "corporate", "https://www.openpr.com/rss/finance-banking-insurance.xml"),
    ("etf_trends_rss", "ETF Trends RSS", "etf", "https://www.etftrends.com/feed/"),
    ("etfdb_rss", "ETF Database RSS", "etf", "https://etfdb.com/feed/"),
    ("spglobal_market_intel_rss", "S&P Global Market Intelligence RSS", "market-news", "https://www.spglobal.com/marketintelligence/en/rss-feed"),
)


NEWS_CONNECTORS: tuple[NewsConnectorSpec, ...] = (
    *API_KEY_NEWS_CONNECTORS,
    *(
        NewsConnectorSpec(slug, name, "public-rss", category, url_template=url)
        for slug, name, category, url in RSS_SOURCES
    ),
)


NEWS_CONNECTOR_SECRET_KEYS = {spec.slug: spec.env_key for spec in API_KEY_NEWS_CONNECTORS if spec.env_key}


class NewsConnectorCatalog:
    """Searchable registry of news connectors."""

    def __init__(self, connectors: tuple[NewsConnectorSpec, ...] = NEWS_CONNECTORS) -> None:
        self._connectors = connectors

    def all(self) -> list[NewsConnectorSpec]:
        return list(self._connectors)

    def get(self, slug: str) -> NewsConnectorSpec | None:
        normalized = slug.strip().lower()
        return next((connector for connector in self._connectors if connector.slug == normalized), None)

    def search(self, query: str) -> list[NewsConnectorSpec]:
        normalized = query.strip().lower()
        if not normalized:
            return self.all()
        return [
            connector
            for connector in self._connectors
            if normalized in connector.slug or normalized in connector.name.lower() or normalized in connector.category
        ]

    def free_first(self) -> list[NewsConnectorSpec]:
        order = {"public-rss": 0, "public-web": 1, "free": 2, "free-tier": 3, "api-key": 4, "custom": 5}
        return sorted(self._connectors, key=lambda connector: (order.get(connector.access, 9), connector.slug))


class NewsConnectorManager:
    """Fetch news from public RSS, free-tier APIs, or custom endpoints."""

    def __init__(
        self,
        catalog: NewsConnectorCatalog | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 8,
    ) -> None:
        self.catalog = catalog or NewsConnectorCatalog()
        self.client = client
        self.timeout_seconds = timeout_seconds

    async def fetch(self, slug: str, symbol: str, limit: int = 10) -> list[NewsItem]:
        spec = self.catalog.get(slug)
        if spec is None:
            raise ProviderError(f"News connector tidak dikenal: {slug}")
        normalized = symbol.upper()
        if spec.access == "public-rss":
            return await self._fetch_rss(spec, normalized, limit)
        if spec.slug == "marketaux":
            return await self._fetch_marketaux(normalized, limit)
        if spec.slug == "newsapi":
            return await self._fetch_newsapi(normalized, limit)
        if spec.slug == "gnews":
            return await self._fetch_gnews(normalized, limit)
        if spec.slug == "alphavantage_news":
            return await self._fetch_alphavantage(normalized, limit)
        if spec.slug == "finnhub_news":
            return await self._fetch_finnhub(normalized, limit)
        if spec.slug == "custom_news":
            return await self._fetch_custom(normalized, limit)
        raise ProviderError(
            f"Adapter aktif untuk {spec.slug} belum tersedia.",
            "Gunakan /news_model list untuk melihat connector aktif atau taruh provider ini di fallback bawah.",
        )

    async def _fetch_rss(self, spec: NewsConnectorSpec, symbol: str, limit: int) -> list[NewsItem]:
        url = spec.url_template.format(symbol=quote_plus(symbol), query=quote_plus(f"{symbol} stock market news"))
        response = await self._get(url)
        return _parse_rss(response.text, spec.name, limit)

    async def _fetch_marketaux(self, symbol: str, limit: int) -> list[NewsItem]:
        key = _required_key("marketaux")
        response = await self._get(
            "https://api.marketaux.com/v1/news/all",
            params={"symbols": symbol, "api_token": key, "limit": limit, "language": "en"},
        )
        return _parse_article_list(response.json().get("data", []), "Marketaux", limit)

    async def _fetch_newsapi(self, symbol: str, limit: int) -> list[NewsItem]:
        key = _required_key("newsapi")
        response = await self._get(
            "https://newsapi.org/v2/everything",
            params={"q": symbol, "apiKey": key, "pageSize": limit, "sortBy": "publishedAt", "language": "en"},
        )
        return _parse_article_list(response.json().get("articles", []), "NewsAPI", limit)

    async def _fetch_gnews(self, symbol: str, limit: int) -> list[NewsItem]:
        key = _required_key("gnews")
        response = await self._get(
            "https://gnews.io/api/v4/search",
            params={"q": symbol, "token": key, "max": min(limit, 10), "lang": "en"},
        )
        return _parse_article_list(response.json().get("articles", []), "GNews", limit)

    async def _fetch_alphavantage(self, symbol: str, limit: int) -> list[NewsItem]:
        key = _required_key("alphavantage_news")
        response = await self._get(
            "https://www.alphavantage.co/query",
            params={"function": "NEWS_SENTIMENT", "tickers": symbol, "apikey": key, "limit": limit},
        )
        return _parse_article_list(response.json().get("feed", []), "Alpha Vantage", limit)

    async def _fetch_finnhub(self, symbol: str, limit: int) -> list[NewsItem]:
        key = _required_key("finnhub_news")
        response = await self._get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": symbol, "from": "2020-01-01", "to": datetime.now(timezone.utc).date().isoformat(), "token": key},
        )
        return _parse_article_list(response.json(), "Finnhub", limit)

    async def _fetch_custom(self, symbol: str, limit: int) -> list[NewsItem]:
        base_url = os.getenv("CUSTOM_NEWS_BASE_URL") or os.getenv("NEWS_DATA_BASE_URL")
        if not base_url:
            raise ProviderError("CUSTOM_NEWS_BASE_URL belum diatur untuk custom_news.")
        key = os.getenv("CUSTOM_NEWS_API_KEY") or os.getenv("NEWS_DATA_API_KEY")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        response = await self._get(f"{base_url.rstrip('/')}/news/{quote_plus(symbol)}", params={"limit": limit}, headers=headers)
        payload = response.json()
        articles = payload.get("items") or payload.get("articles") or payload.get("data") if isinstance(payload, dict) else payload
        return _parse_article_list(articles or [], "Custom News", limit)

    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        if self.client is not None:
            response = await self.client.get(url, timeout=self.timeout_seconds, **kwargs)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = await client.get(url, **kwargs)
        if response.status_code >= 400:
            raise ProviderError(f"News connector HTTP {response.status_code}: {url}")
        return response


def news_connector_secret_key(slug: str) -> str | None:
    return NEWS_CONNECTOR_SECRET_KEYS.get(slug.strip().lower())


def _required_key(slug: str) -> str:
    env_key = news_connector_secret_key(slug)
    if not env_key:
        raise ProviderError(f"Connector {slug} tidak membutuhkan API key.")
    value = os.getenv(env_key)
    if not value:
        raise ProviderError(
            f"API key untuk news connector {slug} belum diatur.",
            f"Gunakan /news_model key {slug} <api_key>.",
        )
    return value


def _parse_rss(xml_text: str, source: str, limit: int) -> list[NewsItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ProviderError(f"RSS dari {source} tidak valid.") from exc
    items: list[NewsItem] = []
    for item in root.findall(".//item")[:limit]:
        title = _clean_text(_xml_text(item, "title"))
        if not title:
            continue
        items.append(
            NewsItem(
                title=title,
                source=source,
                url=_clean_text(_xml_text(item, "link")) or None,
                published_at=_parse_datetime(_xml_text(item, "pubDate") or _xml_text(item, "published")),
                summary=_clean_text(_xml_text(item, "description")),
            )
        )
    return items


def _parse_article_list(articles: Any, source: str, limit: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    if not isinstance(articles, list):
        return items
    for article in articles[:limit]:
        if not isinstance(article, dict):
            continue
        title = _clean_text(str(article.get("title") or article.get("headline") or ""))
        if not title:
            continue
        published = (
            article.get("published_at")
            or article.get("publishedAt")
            or article.get("datetime")
            or article.get("time_published")
            or article.get("date")
        )
        url = article.get("url") or article.get("link")
        source_name = _article_source(article, source)
        items.append(
            NewsItem(
                title=title,
                source=source_name,
                url=str(url) if url else None,
                published_at=_parse_datetime(str(published)) if published is not None else None,
                summary=_clean_text(str(article.get("description") or article.get("summary") or article.get("content") or "")),
            )
        )
    return items


def _article_source(article: dict[str, Any], fallback: str) -> str:
    source = article.get("source")
    if isinstance(source, dict):
        return str(source.get("name") or fallback)
    if source:
        return str(source)
    return fallback


def _xml_text(item: ET.Element, tag: str) -> str:
    child = item.find(tag)
    return child.text if child is not None and child.text else ""


def _parse_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    # YYYYMMDD format must be checked BEFORE Unix timestamp (8-digit numbers like 20240101)
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        except (OSError, ValueError):
            return None
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", unescape(value or ""))
    return re.sub(r"\s+", " ", text).strip()
