"""yfinance fallback provider for delayed public market data."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fincli.app.providers.market.base import (
    BaseMarketProvider,
    Candle,
    FundamentalSnapshot,
    NewsItem,
    ProviderCapability,
    ProviderStatus,
    Quote,
)
from fincli.app.providers.market.symbols import resolve_yfinance_symbol
from fincli.app.utils.errors import ProviderError


@dataclass(frozen=True, slots=True)
class YahooTable:
    symbol: str
    section: str
    columns: list[str]
    rows: list[list[str]]
    source_url: str
    note: str = ""


class YFinanceProvider(BaseMarketProvider):
    name = "yfinance"

    async def quote(self, symbol: str) -> Quote:
        return await asyncio.to_thread(self._quote_sync, symbol)

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return await asyncio.to_thread(self._history_sync, symbol, period, interval)

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return await asyncio.to_thread(self._news_sync, symbol, limit)

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return await asyncio.to_thread(self._fundamentals_sync, symbol)

    async def yahoo_table(
        self,
        symbol: str,
        section: str,
        period: str = "6mo",
        interval: str = "1d",
    ) -> YahooTable:
        return await asyncio.to_thread(self._yahoo_table_sync, symbol, section, period, interval)

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            realtime=False,
            status="fallback",
            message=f"Configured at {datetime.now().isoformat(timespec='seconds')}; yfinance fallback may be delayed.",
        )

    def capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name,
            realtime=False,
            operations=("quote", "history", "news", "fundamentals"),
            asset_classes=("stock", "forex", "crypto", "commodity", "index"),
            rate_limit_note="Unofficial API; may be rate-limited or blocked.",
        )

    def _ticker(self, symbol: str) -> Any:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ProviderError(
                "Dependency yfinance belum terinstall.",
                "Jalankan: pip install -e \".[market]\" atau pip install yfinance pandas numpy",
            ) from exc
        return yf.Ticker(symbol)

    def _quote_sync(self, symbol: str) -> Quote:
        try:
            resolved = resolve_yfinance_symbol(symbol)
            ticker = self._ticker(resolved.symbol)
            info = getattr(ticker, "fast_info", None)
            price = None
            currency = "USD"
            if info is not None:
                price = _safe_float(_safe_get(info, "last_price") or _safe_get(info, "lastPrice"))
                currency = str(_safe_get(info, "currency") or currency)

            if price is None:
                history = ticker.history(period="5d", interval="1d")
                if history.empty:
                    raise ProviderError(f"Data harga kosong untuk {symbol}.", "Coba symbol lain, contoh AAPL atau BTC-USD.")
                price = float(history["Close"].dropna().iloc[-1])

            return Quote(
                symbol=resolved.symbol.upper(),
                price=price,
                currency=currency,
                provider=self.name,
                timestamp=datetime.now(),
                status="delayed",
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Gagal mengambil quote dari yfinance untuk {symbol}: {exc}") from exc

    def _history_sync(self, symbol: str, period: str, interval: str) -> list[Candle]:
        try:
            resolved = resolve_yfinance_symbol(symbol)
            ticker = self._ticker(resolved.symbol)
            frame = ticker.history(period=period, interval=interval)
            if frame.empty:
                raise ProviderError(
                    f"Data OHLCV kosong untuk {symbol} ({resolved.symbol}).",
                    "Coba provider twelvedata/finnhub atau symbol lain, contoh EURUSD, XAUUSD, SPX, AAPL.",
                )

            candles: list[Candle] = []
            for index, row in frame.dropna(subset=["Open", "High", "Low", "Close"]).iterrows():
                timestamp = index.to_pydatetime() if hasattr(index, "to_pydatetime") else datetime.now()
                candles.append(
                    Candle(
                        timestamp=timestamp,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row.get("Volume", 0.0)),
                    )
                )
            return candles
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Gagal mengambil history dari yfinance untuk {symbol}: {exc}") from exc

    def _news_sync(self, symbol: str, limit: int) -> list[NewsItem]:
        try:
            resolved = resolve_yfinance_symbol(symbol)
            ticker = self._ticker(resolved.symbol)
            raw_news = getattr(ticker, "news", []) or []
            items: list[NewsItem] = []
            for item in raw_news[:limit]:
                content = item.get("content", item) if isinstance(item, dict) else {}
                title = str(content.get("title") or item.get("title") or "Untitled")
                provider = content.get("provider") or {}
                source = str(provider.get("displayName") if isinstance(provider, dict) else provider or "yfinance")
                url = content.get("canonicalUrl") or content.get("clickThroughUrl") or item.get("link")
                if isinstance(url, dict):
                    url = url.get("url")
                published_at = None
                timestamp = content.get("pubDate") or item.get("providerPublishTime")
                if isinstance(timestamp, int):
                    published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                elif isinstance(timestamp, str):
                    published_at = _parse_datetime(timestamp)
                summary = str(content.get("summary") or "")
                items.append(NewsItem(title=title, source=source, url=url, published_at=published_at, summary=summary))
            return items
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Gagal mengambil news dari yfinance untuk {symbol}: {exc}") from exc

    def _fundamentals_sync(self, symbol: str) -> FundamentalSnapshot:
        try:
            resolved = resolve_yfinance_symbol(symbol)
            ticker = self._ticker(resolved.symbol)
            info = ticker.info or {}
            return FundamentalSnapshot(
                symbol=resolved.symbol.upper(),
                provider=self.name,
                currency=str(info.get("financialCurrency") or info.get("currency") or "USD"),
                market_cap=_safe_float(info.get("marketCap")),
                pe_ratio=_safe_float(info.get("trailingPE")),
                eps=_safe_float(info.get("trailingEps")),
                revenue=_safe_float(info.get("totalRevenue")),
                beta=_safe_float(info.get("beta")),
                sector=info.get("sector"),
                industry=info.get("industry"),
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Gagal mengambil fundamentals dari yfinance untuk {symbol}: {exc}") from exc

    def _yahoo_table_sync(self, symbol: str, section: str, period: str, interval: str) -> YahooTable:
        resolved = resolve_yfinance_symbol(symbol)
        ticker = self._ticker(resolved.symbol)
        normalized = section.lower().strip()
        source_url = _source_url(resolved.symbol, normalized)

        if normalized in {"history", "historical", "ohlcv"}:
            frame = ticker.history(period=period, interval=interval)
            return _frame_table(resolved.symbol, "history", frame, source_url, max_rows=40)

        if normalized in {"statistics", "stats", "key-statistics", "key_statistics"}:
            info = ticker.info or {}
            rows = [[label, _format_value(info.get(key))] for label, key in _STATISTIC_FIELDS]
            rows = [row for row in rows if row[1] != "N/A"]
            if not rows:
                rows = _dict_rows(info)
            return YahooTable(resolved.symbol.upper(), "statistics", ["Metric", "Value"], rows, source_url)

        if normalized == "profile":
            info = ticker.info or {}
            rows = [[label, _format_value(info.get(key))] for label, key in _PROFILE_FIELDS]
            rows = [row for row in rows if row[1] != "N/A"]
            if not rows:
                rows = _dict_rows(info)
            return YahooTable(resolved.symbol.upper(), "profile", ["Field", "Value"], rows, source_url)

        if normalized in {"financials", "income", "income-statement"}:
            frame = _first_frame(ticker, ("financials", "income_stmt", "quarterly_financials", "quarterly_income_stmt"))
            return _frame_table(resolved.symbol, "financials", frame, source_url, max_rows=30, transpose=False)

        if normalized in {"balance", "balance-sheet", "balance_sheet"}:
            frame = _first_frame(ticker, ("balance_sheet", "quarterly_balance_sheet"))
            return _frame_table(resolved.symbol, "balance-sheet", frame, source_url, max_rows=30, transpose=False)

        if normalized in {"cashflow", "cash-flow", "cash_flow"}:
            frame = _first_frame(ticker, ("cashflow", "cash_flow", "quarterly_cashflow", "quarterly_cash_flow"))
            return _frame_table(resolved.symbol, "cashflow", frame, source_url, max_rows=30, transpose=False)

        if normalized == "analysis":
            return self._analysis_table(ticker, resolved.symbol, source_url)

        if normalized == "holders":
            return self._holders_table(ticker, resolved.symbol, source_url)

        if normalized == "news":
            news = self._news_sync(symbol, limit=10)
            rows = [
                [
                    item.title,
                    item.source,
                    item.published_at.isoformat(timespec="seconds") if item.published_at else "unknown",
                    item.url or "-",
                ]
                for item in news
            ]
            return YahooTable(resolved.symbol.upper(), "news", ["Title", "Source", "Published", "URL"], rows, source_url)

        raise ProviderError(
            f"Yahoo section tidak dikenal: {section}",
            "Gunakan: history, statistics, profile, financials, balance, cashflow, analysis, holders, news.",
        )

    def _analysis_table(self, ticker: Any, symbol: str, source_url: str) -> YahooTable:
        rows: list[list[str]] = []
        targets = _safe_get(ticker, "analyst_price_targets") or {}
        if isinstance(targets, dict):
            for key, value in targets.items():
                rows.append(["Price Target", str(key), _format_value(value)])

        recommendations = _safe_get(ticker, "recommendations")
        rec_rows = _frame_rows(recommendations, max_rows=15)
        rows.extend([["Recommendations", *row] for row in rec_rows])

        upgrades = _safe_get(ticker, "upgrades_downgrades")
        upgrade_rows = _frame_rows(upgrades, max_rows=15)
        rows.extend([["Upgrades/Downgrades", *row] for row in upgrade_rows])

        if not rows:
            info = _safe_get(ticker, "info") or {}
            rows = [
                ["Analyst Rating", "recommendationKey", _format_value(info.get("recommendationKey"))],
                ["Analyst Count", "numberOfAnalystOpinions", _format_value(info.get("numberOfAnalystOpinions"))],
                ["Target Mean", "targetMeanPrice", _format_value(info.get("targetMeanPrice"))],
                ["Target High", "targetHighPrice", _format_value(info.get("targetHighPrice"))],
                ["Target Low", "targetLowPrice", _format_value(info.get("targetLowPrice"))],
            ]
            rows = [row for row in rows if row[-1] != "N/A"]

        return YahooTable(
            symbol.upper(),
            "analysis",
            ["Section", "Field", "Value", "Extra 1", "Extra 2", "Extra 3"],
            _pad_rows(rows, 6),
            source_url,
            "Yahoo analysis availability varies by exchange and ticker.",
        )

    def _holders_table(self, ticker: Any, symbol: str, source_url: str) -> YahooTable:
        rows: list[list[str]] = []
        for label, attr in (
            ("Major Holders", "major_holders"),
            ("Institutional Holders", "institutional_holders"),
            ("Mutual Fund Holders", "mutualfund_holders"),
            ("Insider Transactions", "insider_transactions"),
        ):
            frame_rows = _frame_rows(_safe_get(ticker, attr), max_rows=15)
            rows.extend([[label, *row] for row in frame_rows])
        return YahooTable(
            symbol.upper(),
            "holders",
            ["Section", "Column 1", "Column 2", "Column 3", "Column 4", "Column 5"],
            _pad_rows(rows, 6),
            source_url,
            "Holder data availability varies by exchange and Yahoo coverage.",
        )


_STATISTIC_FIELDS = (
    ("Market Cap", "marketCap"),
    ("Enterprise Value", "enterpriseValue"),
    ("Trailing P/E", "trailingPE"),
    ("Forward P/E", "forwardPE"),
    ("PEG Ratio", "pegRatio"),
    ("Price/Sales", "priceToSalesTrailing12Months"),
    ("Price/Book", "priceToBook"),
    ("EPS", "trailingEps"),
    ("Forward EPS", "forwardEps"),
    ("Revenue", "totalRevenue"),
    ("Gross Margins", "grossMargins"),
    ("Operating Margins", "operatingMargins"),
    ("Profit Margins", "profitMargins"),
    ("Return on Assets", "returnOnAssets"),
    ("Return on Equity", "returnOnEquity"),
    ("Dividend Yield", "dividendYield"),
    ("Beta", "beta"),
    ("52 Week High", "fiftyTwoWeekHigh"),
    ("52 Week Low", "fiftyTwoWeekLow"),
    ("Average Volume", "averageVolume"),
)

_PROFILE_FIELDS = (
    ("Name", "longName"),
    ("Symbol", "symbol"),
    ("Exchange", "exchange"),
    ("Quote Type", "quoteType"),
    ("Currency", "currency"),
    ("Financial Currency", "financialCurrency"),
    ("Country", "country"),
    ("Sector", "sector"),
    ("Industry", "industry"),
    ("Employees", "fullTimeEmployees"),
    ("Website", "website"),
    ("Address", "address1"),
    ("City", "city"),
    ("Phone", "phone"),
    ("Business Summary", "longBusinessSummary"),
)


def _safe_get(obj: Any, key: str) -> Any:
    try:
        return obj[key]
    except Exception:  # noqa: BLE001
        return getattr(obj, key, None)


def _source_url(symbol: str, section: str) -> str:
    encoded = symbol.upper().replace("^", "%5E")
    suffix = {
        "history": "history",
        "historical": "history",
        "ohlcv": "history",
        "statistics": "key-statistics",
        "stats": "key-statistics",
        "key-statistics": "key-statistics",
        "key_statistics": "key-statistics",
        "profile": "profile",
        "financials": "financials",
        "income": "financials",
        "income-statement": "financials",
        "balance": "balance-sheet",
        "balance-sheet": "balance-sheet",
        "balance_sheet": "balance-sheet",
        "cashflow": "cash-flow",
        "cash-flow": "cash-flow",
        "cash_flow": "cash-flow",
        "analysis": "analysis",
        "holders": "holders",
        "news": "news",
    }.get(section, section)
    return f"https://finance.yahoo.com/quote/{encoded}/{suffix}/"


def _frame_table(
    symbol: str,
    section: str,
    frame: Any,
    source_url: str,
    max_rows: int = 25,
    max_cols: int = 8,
    transpose: bool = False,
) -> YahooTable:
    if frame is None or getattr(frame, "empty", True):
        return YahooTable(symbol.upper(), section, ["Info"], [["No data returned by yfinance/Yahoo."]], source_url)
    data = frame.T if transpose else frame
    rows = _frame_rows(data, max_rows=max_rows, max_cols=max_cols)
    columns = _frame_columns(data, max_cols=max_cols)
    return YahooTable(symbol.upper(), section, columns, rows, source_url)


def _frame_columns(frame: Any, max_cols: int = 8) -> list[str]:
    try:
        reset = frame.reset_index()
        return [_stringify(column) for column in list(reset.columns[:max_cols])]
    except Exception:  # noqa: BLE001
        return ["Column 1", "Column 2"]


def _frame_rows(frame: Any, max_rows: int = 25, max_cols: int = 8) -> list[list[str]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    try:
        reset = frame.reset_index()
        rows: list[list[str]] = []
        for _, row in reset.head(max_rows).iterrows():
            rows.append([_format_value(value) for value in list(row.iloc[:max_cols])])
        return rows
    except Exception:  # noqa: BLE001
        return []


def _first_frame(ticker: Any, attrs: tuple[str, ...]) -> Any:
    for attr in attrs:
        frame = _safe_get(ticker, attr)
        if frame is not None and not getattr(frame, "empty", True):
            return frame
    return None


def _dict_rows(data: dict[str, Any], max_rows: int = 40) -> list[list[str]]:
    rows = []
    for key, value in list(data.items())[:max_rows]:
        if value is None or isinstance(value, (dict, list, tuple, set)):
            continue
        rows.append([_stringify(key), _format_value(value)])
    return rows


def _pad_rows(rows: list[list[str]], columns: int) -> list[list[str]]:
    return [row[:columns] + [""] * max(0, columns - len(row)) for row in rows]


def _format_value(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        if hasattr(value, "isoformat"):
            return value.isoformat()
    except Exception:  # noqa: BLE001
        pass
    if isinstance(value, float):
        return f"{value:,.4f}"
    if isinstance(value, int):
        return f"{value:,}"
    text = str(value)
    return text[:500] + "..." if len(text) > 500 else text


def _stringify(value: Any) -> str:
    return str(value)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
