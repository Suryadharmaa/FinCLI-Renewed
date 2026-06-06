"""Exportable market report helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fincli.app.services.market_overview import MarketOverview
from fincli.app.utils.errors import CommandError


def write_market_report(overview: MarketOverview, fmt: str, target: str | Path) -> Path:
    report_format = fmt.lower()
    path = _safe_report_path(target, report_format)
    path.parent.mkdir(parents=True, exist_ok=True)
    if report_format == "json":
        path.write_text(json.dumps(_overview_payload(overview), indent=2, default=str), encoding="utf-8")
        return path
    if report_format in {"md", "markdown"}:
        path.write_text(_overview_markdown(overview), encoding="utf-8")
        return path
    raise CommandError("Report format must be md or json.")


def _safe_report_path(target: str | Path, fmt: str) -> Path:
    path = Path(target).expanduser()
    if any(part == ".." for part in path.parts):
        raise CommandError("Report path must not contain '..'.")
    allowed = {".md", ".json"} if fmt in {"md", "markdown", "json"} else set()
    if path.suffix.lower() not in allowed:
        raise CommandError("Report path must end with .md or .json.")
    return path


def _overview_payload(overview: MarketOverview) -> dict[str, Any]:
    return {
        "symbol": overview.symbol,
        "timeframe": overview.timeframe,
        "quote": {
            "symbol": overview.quote.symbol,
            "price": overview.quote.price,
            "currency": overview.quote.currency,
            "provider": overview.quote.provider,
            "status": overview.quote.status,
            "timestamp": overview.quote.timestamp.isoformat(),
        },
        "data_quality": {
            "score": overview.data_quality.score,
            "quote": overview.data_quality.quote,
            "ohlcv": overview.data_quality.ohlcv,
            "news": overview.data_quality.news,
            "fundamentals": overview.data_quality.fundamentals,
            "provider": overview.data_quality.provider,
        },
        "technical": {
            "latest_close": overview.technical.latest_close,
            "trend_bias": overview.technical.trend_bias,
            "rsi": overview.technical.rsi,
            "macd": overview.technical.macd,
            "macd_signal": overview.technical.macd_signal,
            "atr": overview.technical.atr,
            "support": overview.technical.support,
            "resistance": overview.technical.resistance,
        },
        "structure": {
            "trend": overview.structure.trend,
            "latest_pattern": overview.structure.latest_pattern,
            "break_of_structure": overview.structure.break_of_structure,
            "change_of_character": overview.structure.change_of_character,
            "liquidity_area": overview.structure.liquidity_area,
            "risk_zone": overview.structure.risk_zone,
        },
        "fundamentals": None
        if overview.fundamentals is None
        else {
            "provider": overview.fundamentals.provider,
            "currency": overview.fundamentals.currency,
            "market_cap": overview.fundamentals.market_cap,
            "pe_ratio": overview.fundamentals.pe_ratio,
            "eps": overview.fundamentals.eps,
            "revenue": overview.fundamentals.revenue,
            "sector": overview.fundamentals.sector,
            "industry": overview.fundamentals.industry,
        },
        "news": [
            {
                "title": item.title,
                "source": item.source,
                "url": item.url,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "summary": item.summary,
            }
            for item in overview.news
        ],
        "disclaimer": "Informational only. Not financial advice.",
    }


def _overview_markdown(overview: MarketOverview) -> str:
    payload = _overview_payload(overview)
    news_lines = "\n".join(
        f"- {item['title']} ({item['source']})" + (f" - {item['url']}" if item["url"] else "")
        for item in payload["news"]
    )
    fundamentals = payload["fundamentals"] or {}
    return "\n".join(
        [
            f"# FinCLI Market Report: {overview.symbol}",
            "",
            f"- Timeframe: {overview.timeframe}",
            f"- Provider: {overview.quote.provider} ({overview.quote.status})",
            f"- Data Quality: {overview.data_quality.score}/100",
            "",
            "## Quote",
            "",
            f"- Price: {overview.quote.price} {overview.quote.currency}",
            f"- Timestamp: {overview.quote.timestamp.isoformat(timespec='seconds')}",
            "",
            "## Technical",
            "",
            f"- Trend Bias: {overview.technical.trend_bias}",
            f"- RSI: {overview.technical.rsi}",
            f"- MACD: {overview.technical.macd} / {overview.technical.macd_signal}",
            f"- ATR: {overview.technical.atr}",
            f"- Support / Resistance: {overview.technical.support} / {overview.technical.resistance}",
            "",
            "## Market Structure",
            "",
            f"- Trend: {overview.structure.trend}",
            f"- Pattern: {overview.structure.latest_pattern}",
            f"- BOS / CHoCH: {overview.structure.break_of_structure} / {overview.structure.change_of_character}",
            f"- Liquidity Area: {overview.structure.liquidity_area}",
            f"- Risk Zone: {overview.structure.risk_zone}",
            "",
            "## Fundamentals",
            "",
            f"- Sector / Industry: {fundamentals.get('sector', 'N/A')} / {fundamentals.get('industry', 'N/A')}",
            f"- Market Cap: {fundamentals.get('market_cap', 'N/A')}",
            f"- P/E / EPS: {fundamentals.get('pe_ratio', 'N/A')} / {fundamentals.get('eps', 'N/A')}",
            "",
            "## Latest News",
            "",
            news_lines or "- No recent news returned by provider.",
            "",
            "## Disclaimer",
            "",
            "Informational only. Not financial advice.",
            "",
        ]
    )
