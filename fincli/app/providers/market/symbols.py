"""Provider-specific symbol normalization for multi-asset market data."""

from __future__ import annotations

from dataclasses import dataclass


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


def resolve_yfinance_symbol(symbol: str) -> ResolvedSymbol:
    normalized = _normalize(symbol)
    if normalized in YFINANCE_ALIASES:
        return ResolvedSymbol(symbol, YFINANCE_ALIASES[normalized], _alias_class(normalized))
    if normalized in IDX_ALIASES:
        return ResolvedSymbol(symbol, f"{normalized}.JK", "stock")
    if _is_metal_pair(normalized) or _is_forex_pair(normalized):
        return ResolvedSymbol(symbol, f"{normalized}=X", "forex")
    return ResolvedSymbol(symbol, symbol.upper(), "stock")


def resolve_twelvedata_symbol(symbol: str) -> ResolvedSymbol:
    normalized = _normalize(symbol)
    if normalized in TWELVEDATA_ALIASES:
        return ResolvedSymbol(symbol, TWELVEDATA_ALIASES[normalized], _alias_class(normalized))
    if _is_metal_pair(normalized) or _is_forex_pair(normalized):
        return ResolvedSymbol(symbol, f"{normalized[:3]}/{normalized[3:]}", "forex")
    if "/" in symbol or ":" in symbol:
        return ResolvedSymbol(symbol, symbol.upper(), "custom")
    return ResolvedSymbol(symbol, symbol.upper(), "stock")


def resolve_finnhub_symbol(symbol: str) -> ResolvedSymbol:
    normalized = _normalize(symbol)
    if _is_forex_pair(normalized):
        return ResolvedSymbol(symbol, f"OANDA:{normalized[:3]}_{normalized[3:]}", "forex")
    if normalized.startswith("BINANCE:"):
        return ResolvedSymbol(symbol, normalized, "crypto")
    if normalized.endswith("USDT") and len(normalized) > 6:
        return ResolvedSymbol(symbol, f"BINANCE:{normalized}", "crypto")
    return ResolvedSymbol(symbol, symbol.upper(), "stock")


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
