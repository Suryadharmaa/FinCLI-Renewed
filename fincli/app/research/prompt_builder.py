"""Prompt builder for deep research mode."""

from __future__ import annotations

from fincli.app.research.models import ResearchBrief


RESEARCH_WORKSPACE_PROMPT = """
You are FinCLI Research Workspace, operating as Research Engine v2.

Rules:
- Build a concise investment/trading research note from the provided data only.
- Output must focus on snapshot, signal, risk, missing data, source quality.
- Obey the Data Trust Gate. If it says caution/no directional signal, do not produce buy/sell conviction.
- Do not invent price, news, fundamentals, or certainty.
- Do not copy the opening summary as the final summary.
- Prioritize decision-useful points over long explanation.
- Separate facts, interpretation, and risk.
- Keep output short: max 8 bullets plus final summary.
- Use slash-command context correctly: FinCLI commands start with "/", not "fincli".
- This is educational market research, not financial advice.
""".strip()


def build_research_prompt(brief: ResearchBrief) -> str:
    overview = brief.overview
    news = "\n".join(f"- {item.title} ({item.source}) {item.summary}" for item in overview.news) or "- No news."
    fundamentals = overview.fundamentals
    fundamentals_text = (
        "No fundamentals."
        if fundamentals is None
        else (
            f"market_cap={fundamentals.market_cap}; pe={fundamentals.pe_ratio}; eps={fundamentals.eps}; "
            f"revenue={fundamentals.revenue}; sector={fundamentals.sector}; industry={fundamentals.industry}"
        )
    )
    return (
        f"{RESEARCH_WORKSPACE_PROMPT}\n\n"
        f"Symbol: {brief.symbol}\n"
        f"Mode: {brief.mode}\n"
        "Required focus: snapshot, signal, risk, missing data, source quality.\n"
        f"Snapshot: {brief.snapshot}\n"
        f"Signal: {brief.signal}\n"
        f"Risk: {brief.risk}\n"
        f"Data Trust Gate: {brief.trust_gate}\n"
        f"Missing Data: {brief.missing_data}\n"
        f"Source Quality: {brief.source_quality}\n"
        f"Quote: {overview.quote.price} {overview.quote.currency} via {overview.quote.provider} ({overview.quote.status})\n"
        f"Data Quality: {overview.data_quality.score}/100; OHLCV={overview.data_quality.ohlcv}; News={overview.data_quality.news}; Fundamentals={overview.data_quality.fundamentals}\n"
        f"Technical: trend={overview.technical.trend_bias}; rsi={overview.technical.rsi}; macd={overview.technical.macd}; support={overview.technical.support}; resistance={overview.technical.resistance}; atr={overview.technical.atr}\n"
        f"Structure: trend={overview.structure.trend}; pattern={overview.structure.latest_pattern}; bos={overview.structure.break_of_structure}; choch={overview.structure.change_of_character}\n"
        f"Decision Points:\n{chr(10).join(f'- {point}' for point in brief.decision_points)}\n"
        f"Risks:\n{chr(10).join(f'- {risk}' for risk in brief.risks)}\n"
        f"News:\n{news}\n"
        f"Fundamentals: {fundamentals_text}\n"
    )
