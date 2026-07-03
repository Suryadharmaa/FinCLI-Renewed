"""Provider-specific symbol normalization for multi-asset market data."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.providers.market.base import SymbolSearchResult

FOREX_CURRENCIES = {
    "AUD",
    "CAD",
    "CHF",
    "CNH",
    "CNY",
    "EUR",
    "GBP",
    "HKD",
    "JPY",
    "MXN",
    "NOK",
    "NZD",
    "SEK",
    "SGD",
    "USD",
    "ZAR",
}

YFINANCE_ALIASES = {
    "SPX": "^GSPC",
    "SP500": "^GSPC",
    "S&P500": "^GSPC",
    "NASDAQ": "^IXIC",
    "IXIC": "^IXIC",
    "NDX": "^NDX",
    "DOW": "^DJI",
    "DJI": "^DJI",
    "RUSSELL2000": "^RUT",
    "VIX": "^VIX",
    "DAX": "^GDAXI",
    "FTSE": "^FTSE",
    "CAC40": "^FCHI",
    "NIKKEI": "^N225",
    "N225": "^N225",
    "HSI": "^HSI",
    "HANGSENG": "^HSI",
    "STI": "^STI",
    "KOSPI": "^KS11",
    "ASX200": "^AXJO",
    "STOXX50": "^STOXX50E",
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "WTI": "CL=F",
    "BRENT": "BZ=F",
    "NATGAS": "NG=F",
    "COPPER": "HG=F",
    "CORN": "ZC=F",
    "SOYBEAN": "ZS=F",
}

IDX_ALIASES = {
    "ACES",
    "ADRO",
    "AKRA",
    "AMMN",
    "ANTM",
    "ARTO",
    "ASII",
    "BBCA",
    "BBNI",
    "BBRI",
    "BBTN",
    "BMRI",
    "BRIS",
    "BRPT",
    "BUKA",
    "CPIN",
    "EMTK",
    "ESSA",
    "EXCL",
    "GGRM",
    "GOTO",
    "HRUM",
    "ICBP",
    "INCO",
    "INDF",
    "INKP",
    "INTP",
    "ITMG",
    "JPFA",
    "JSMR",
    "KLBF",
    "MDKA",
    "MEDC",
    "PGAS",
    "PTBA",
    "SIDO",
    "SMGR",
    "TINS",
    "TLKM",
    "TOWR",
    "UNTR",
    "UNVR",
}

TWELVEDATA_ALIASES = {
    "SPX": "SPX",
    "SP500": "SPX",
    "S&P500": "SPX",
    "NASDAQ": "IXIC",
    "IXIC": "IXIC",
    "NDX": "NDX",
    "DOW": "DJI",
    "DJI": "DJI",
    "DAX": "DAX",
    "FTSE": "FTSE",
    "CAC40": "CAC",
    "NIKKEI": "N225",
    "HSI": "HSI",
    "GOLD": "XAU/USD",
    "SILVER": "XAG/USD",
    "WTI": "WTI/USD",
    "BRENT": "BRENT/USD",
}


@dataclass(frozen=True, slots=True)
class ResolvedSymbol:
    original: str
    symbol: str
    asset_class: str
    provider_symbols: dict[str, str] | None = None
    confidence: str = "rule"
    source: str = "local_rules"
    notes: str = ""

    @property
    def canonical(self) -> str:
        return self.symbol


@dataclass(frozen=True, slots=True)
class SymbolAlias:
    symbol: str
    name: str
    asset_class: str
    exchange: str = ""
    currency: str = ""
    aliases: tuple[str, ...] = ()
    notes: str = ""


SYMBOL_CATALOG: tuple[SymbolAlias, ...] = (
    SymbolAlias("AAPL", "Apple Inc.", "stock", "NASDAQ", "USD", ("APPLE",)),
    SymbolAlias("MSFT", "Microsoft Corporation", "stock", "NASDAQ", "USD", ("MICROSOFT",)),
    SymbolAlias("NVDA", "NVIDIA Corporation", "stock", "NASDAQ", "USD", ("NVIDIA",)),
    SymbolAlias("TSLA", "Tesla Inc.", "stock", "NASDAQ", "USD", ("TESLA",)),
    SymbolAlias("SPY", "SPDR S&P 500 ETF Trust", "etf", "NYSE Arca", "USD", ("S&P ETF",)),
    SymbolAlias("QQQ", "Invesco QQQ Trust", "etf", "NASDAQ", "USD", ("NASDAQ ETF",)),
    SymbolAlias("SPX", "S&P 500 Index", "index", "US", "USD", ("SP500", "S&P500", "^GSPC")),
    SymbolAlias("US500", "S&P 500 CFD alias", "index", "US", "USD", ("SPX", "SP500", "^GSPC")),
    SymbolAlias("NASDAQ", "Nasdaq Composite Index", "index", "US", "USD", ("IXIC", "^IXIC")),
    SymbolAlias("US100", "Nasdaq 100 CFD alias", "index", "US", "USD", ("NDX", "NASDAQ100", "^NDX")),
    SymbolAlias("DOW", "Dow Jones Industrial Average", "index", "US", "USD", ("DJI", "^DJI")),
    SymbolAlias("US30", "Dow Jones CFD alias", "index", "US", "USD", ("DOW", "DJI", "^DJI")),
    SymbolAlias("DAX", "DAX Performance Index", "index", "Germany", "EUR", ("^GDAXI",)),
    SymbolAlias("NIKKEI", "Nikkei 225 Index", "index", "Japan", "JPY", ("N225", "^N225")),
    SymbolAlias("EURUSD", "Euro / US Dollar", "forex", "FX", "USD", ("EUR/USD", "EURUSD=X")),
    SymbolAlias("GBPUSD", "British Pound / US Dollar", "forex", "FX", "USD", ("GBP/USD", "GBPUSD=X")),
    SymbolAlias("USDJPY", "US Dollar / Japanese Yen", "forex", "FX", "JPY", ("USD/JPY", "USDJPY=X")),
    SymbolAlias("XAUUSD", "Gold Spot / US Dollar", "commodity", "Metals", "USD", ("GOLD", "XAU/USD", "GC=F")),
    SymbolAlias("XAGUSD", "Silver Spot / US Dollar", "commodity", "Metals", "USD", ("SILVER", "XAG/USD", "SI=F")),
    SymbolAlias("WTI", "WTI Crude Oil Futures", "commodity", "NYMEX", "USD", ("CL=F", "OIL")),
    SymbolAlias("BRENT", "Brent Crude Oil Futures", "commodity", "ICE", "USD", ("BZ=F",)),
    SymbolAlias("BTC-USD", "Bitcoin / US Dollar", "crypto", "Crypto", "USD", ("BTCUSD", "BTCUSDT", "BINANCE:BTCUSDT")),
    SymbolAlias("ETH-USD", "Ethereum / US Dollar", "crypto", "Crypto", "USD", ("ETHUSD", "ETHUSDT", "BINANCE:ETHUSDT")),
    SymbolAlias("BBRI", "Bank Rakyat Indonesia", "stock", "IDX", "IDR", ("BBRI.JK",)),
    SymbolAlias("BBCA", "Bank Central Asia", "stock", "IDX", "IDR", ("BBCA.JK",)),
    SymbolAlias("BMRI", "Bank Mandiri", "stock", "IDX", "IDR", ("BMRI.JK",)),
    SymbolAlias("TLKM", "Telkom Indonesia", "stock", "IDX", "IDR", ("TLKM.JK",)),
)


class SymbolResolver:
    """Resolve user-facing symbols to provider-specific symbols with a small local cache."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str], ResolvedSymbol] = {}
        self._search_cache: dict[tuple[str, int], list[SymbolSearchResult]] = {}

    def resolve(self, symbol: str, provider: str = "yfinance", asset_class: str | None = None) -> ResolvedSymbol:
        provider_name = provider.lower().strip()
        asset_hint = (asset_class or "").lower().strip()
        cache_key = (provider_name, _normalize(symbol), asset_hint)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        resolved = resolve_provider_symbol(provider_name, symbol)
        if asset_hint and resolved.asset_class != asset_hint:
            resolved = ResolvedSymbol(
                original=resolved.original,
                symbol=resolved.symbol,
                asset_class=asset_hint,
                provider_symbols=resolved.provider_symbols,
                confidence=resolved.confidence,
                source=resolved.source,
                notes=f"Asset class forced by user: {asset_hint}.",
            )
        self._cache[cache_key] = resolved
        return resolved

    def provider_symbol(self, provider: str, symbol: str, asset_class: str | None = None) -> str:
        return self.resolve(symbol, provider=provider, asset_class=asset_class).symbol

    def matrix(self, symbol: str, providers: tuple[str, ...] | None = None) -> dict[str, ResolvedSymbol]:
        names = providers or ("yfinance", "twelvedata", "finnhub", "alphavantage", "custom")
        return {name: self.resolve(symbol, provider=name) for name in names}

    def search(self, query: str, limit: int = 12) -> list[SymbolSearchResult]:
        cache_key = (_normalize(query), limit)
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return cached
        results = search_symbol_catalog(query, limit=limit)
        self._search_cache[cache_key] = results
        return results


def resolve_yfinance_symbol(symbol: str) -> ResolvedSymbol:
    normalized = _normalize(symbol)
    if normalized in {"US500", "SPX500"}:
        return ResolvedSymbol(symbol, "^GSPC", "index")
    if normalized in {"US100", "NASDAQ100"}:
        return ResolvedSymbol(symbol, "^NDX", "index")
    if normalized == "US30":
        return ResolvedSymbol(symbol, "^DJI", "index")
    if normalized in {"XAUUSD", "GOLD"}:
        return ResolvedSymbol(symbol, "GC=F", "commodity", notes="Yahoo Finance uses gold futures as the practical free fallback for XAUUSD.")
    if normalized in {"XAGUSD", "SILVER"}:
        return ResolvedSymbol(symbol, "SI=F", "commodity", notes="Yahoo Finance uses silver futures as the practical free fallback for XAGUSD.")
    if normalized in {"BTCUSD", "BTCUSDT", "BTC"}:
        return ResolvedSymbol(symbol, "BTC-USD", "crypto")
    if normalized in {"ETHUSD", "ETHUSDT", "ETH"}:
        return ResolvedSymbol(symbol, "ETH-USD", "crypto")
    if normalized in YFINANCE_ALIASES:
        return ResolvedSymbol(symbol, YFINANCE_ALIASES[normalized], _alias_class(normalized))
    if normalized in IDX_ALIASES:
        return ResolvedSymbol(symbol, f"{normalized}.JK", "stock")
    if _is_metal_pair(normalized) or _is_forex_pair(normalized):
        return ResolvedSymbol(symbol, f"{normalized}=X", "forex")
    return ResolvedSymbol(symbol, symbol.upper(), "stock")


def resolve_twelvedata_symbol(symbol: str) -> ResolvedSymbol:
    normalized = _normalize(symbol)
    if normalized in {"US500", "SPX500"}:
        return ResolvedSymbol(symbol, "SPX", "index")
    if normalized in {"US100", "NASDAQ100"}:
        return ResolvedSymbol(symbol, "NDX", "index")
    if normalized == "US30":
        return ResolvedSymbol(symbol, "DJI", "index")
    if normalized in {"BTCUSD", "BTCUSDT", "BTC"}:
        return ResolvedSymbol(symbol, "BTC/USD", "crypto")
    if normalized in {"ETHUSD", "ETHUSDT", "ETH"}:
        return ResolvedSymbol(symbol, "ETH/USD", "crypto")
    if normalized in TWELVEDATA_ALIASES:
        return ResolvedSymbol(symbol, TWELVEDATA_ALIASES[normalized], _alias_class(normalized))
    if _is_metal_pair(normalized) or _is_forex_pair(normalized):
        return ResolvedSymbol(symbol, f"{normalized[:3]}/{normalized[3:]}", "forex")
    if "/" in symbol or ":" in symbol:
        return ResolvedSymbol(symbol, symbol.upper(), "custom")
    return ResolvedSymbol(symbol, symbol.upper(), "stock")


def resolve_finnhub_symbol(symbol: str) -> ResolvedSymbol:
    normalized = _normalize(symbol)
    if normalized in {"US500", "SPX", "SP500", "SPX500"}:
        return ResolvedSymbol(symbol, "^GSPC", "index")
    if normalized in {"US100", "NDX", "NASDAQ100"}:
        return ResolvedSymbol(symbol, "^NDX", "index")
    if normalized in {"US30", "DOW", "DJI"}:
        return ResolvedSymbol(symbol, "^DJI", "index")
    if normalized in {"BTCUSD", "BTCUSDT", "BTC"}:
        return ResolvedSymbol(symbol, "BINANCE:BTCUSDT", "crypto")
    if normalized in {"ETHUSD", "ETHUSDT", "ETH"}:
        return ResolvedSymbol(symbol, "BINANCE:ETHUSDT", "crypto")
    if _is_metal_pair(normalized):
        return ResolvedSymbol(symbol, f"OANDA:{normalized[:3]}_{normalized[3:]}", "commodity")
    if _is_forex_pair(normalized):
        return ResolvedSymbol(symbol, f"OANDA:{normalized[:3]}_{normalized[3:]}", "forex")
    if normalized.startswith("BINANCE:"):
        return ResolvedSymbol(symbol, normalized, "crypto")
    if normalized.endswith("USDT") and len(normalized) > 6:
        return ResolvedSymbol(symbol, f"BINANCE:{normalized}", "crypto")
    return ResolvedSymbol(symbol, symbol.upper(), "stock")


def resolve_provider_symbol(provider: str, symbol: str) -> ResolvedSymbol:
    provider_name = provider.lower().strip()
    if provider_name == "yfinance":
        return resolve_yfinance_symbol(symbol)
    if provider_name == "twelvedata":
        return resolve_twelvedata_symbol(symbol)
    if provider_name == "finnhub":
        return resolve_finnhub_symbol(symbol)
    if provider_name == "alphavantage":
        normalized = _normalize(symbol)
        if normalized in {"US500", "SPX500"}:
            return ResolvedSymbol(symbol, "SPX", "index")
        if normalized in {"US100", "NASDAQ100"}:
            return ResolvedSymbol(symbol, "NDX", "index")
        if normalized == "US30":
            return ResolvedSymbol(symbol, "DJI", "index")
        if normalized in {"BTC", "BTCUSD", "BTCUSDT"}:
            return ResolvedSymbol(symbol, "BTCUSD", "crypto")
        if normalized in {"ETH", "ETHUSD", "ETHUSDT"}:
            return ResolvedSymbol(symbol, "ETHUSD", "crypto")
        if _is_metal_pair(normalized):
            return ResolvedSymbol(symbol, normalized, "commodity")
        if _is_forex_pair(normalized):
            return ResolvedSymbol(symbol, normalized, "forex")
        if normalized in IDX_ALIASES:
            return ResolvedSymbol(symbol, normalized, "stock")
        return ResolvedSymbol(symbol, symbol.strip().upper(), _infer_asset_class(normalized))
    if provider_name == "custom":
        normalized = symbol.strip().upper()
        return ResolvedSymbol(symbol, normalized, _infer_asset_class(normalized))
    raise ValueError(f"Unknown market provider: {provider}")


def provider_symbol_matrix(symbol: str, providers: tuple[str, ...] | None = None) -> dict[str, ResolvedSymbol]:
    return SymbolResolver().matrix(symbol, providers)


def search_symbol_catalog(query: str, limit: int = 12) -> list[SymbolSearchResult]:
    normalized = _normalize(query)
    if not normalized:
        return []

    matches: list[tuple[int, SymbolAlias]] = []
    for item in SYMBOL_CATALOG:
        haystack = [item.symbol, item.name, item.asset_class, item.exchange, item.currency, *item.aliases]
        normalized_haystack = [_normalize(part) for part in haystack if part]
        score = _match_score(normalized, normalized_haystack)
        if score > 0:
            matches.append((score, item))

    matches.sort(key=lambda pair: (-pair[0], pair[1].symbol))
    results = [_symbol_alias_to_result(item) for _, item in matches[:limit]]
    if results:
        return results

    guessed = symbol_search_result(query)
    return [guessed] if guessed else []


def symbol_search_result(symbol: str) -> SymbolSearchResult:
    matrix = provider_symbol_matrix(symbol)
    first = next(iter(matrix.values()))
    return SymbolSearchResult(
        symbol=symbol.upper(),
        name=f"{symbol.upper()} (inferred)",
        asset_class=first.asset_class,
        provider_symbols={provider: resolved.symbol for provider, resolved in matrix.items()},
        notes="Inferred from symbol pattern. Verify exchange/provider entitlement before relying on it.",
    )


def _normalize(symbol: str) -> str:
    return symbol.strip().upper().replace(" ", "").replace("-", "").replace("_", "").replace("/", "")


def _is_forex_pair(symbol: str) -> bool:
    return len(symbol) == 6 and symbol[:3] in FOREX_CURRENCIES and symbol[3:] in FOREX_CURRENCIES


def _is_metal_pair(symbol: str) -> bool:
    return len(symbol) == 6 and symbol[:3] in {"XAU", "XAG", "XPT", "XPD"} and symbol[3:] in FOREX_CURRENCIES


def _alias_class(symbol: str) -> str:
    if symbol in {"GOLD", "SILVER", "WTI", "BRENT", "NATGAS", "COPPER", "CORN", "SOYBEAN"}:
        return "commodity"
    if symbol.startswith("XAU") or symbol.startswith("XAG"):
        return "commodity"
    return "index"


def _symbol_alias_to_result(item: SymbolAlias) -> SymbolSearchResult:
    matrix = provider_symbol_matrix(item.symbol)
    return SymbolSearchResult(
        symbol=item.symbol,
        name=item.name,
        asset_class=item.asset_class,
        exchange=item.exchange,
        currency=item.currency,
        provider_symbols={provider: resolved.symbol for provider, resolved in matrix.items()},
        notes=item.notes,
    )


def _match_score(query: str, haystack: list[str]) -> int:
    score = 0
    for value in haystack:
        if value == query:
            score = max(score, 100)
        elif value.startswith(query):
            score = max(score, 80)
        elif query in value:
            score = max(score, 50)
    return score


def _infer_asset_class(symbol: str) -> str:
    normalized = _normalize(symbol)
    if _is_metal_pair(normalized):
        return "commodity"
    if _is_forex_pair(normalized):
        return "forex"
    if normalized.endswith("USDT") or normalized.endswith("USD") and normalized[:3] in {"BTC", "ETH", "SOL", "BNB"}:
        return "crypto"
    if normalized.startswith("^") or normalized in YFINANCE_ALIASES:
        return "index"
    return "stock"
