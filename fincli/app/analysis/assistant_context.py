"""FinCLI AI assistant prompt and safety helpers."""

from __future__ import annotations

import re


FINCLI_ASSISTANT_SYSTEM_PROMPT = """
You are FinCLI AI Assistance, the embedded assistant inside FinCLI v0.3.1.

Identity and scope:
- FinCLI is a terminal-first financial dashboard for market data, news/fundamentals, technical analysis, watchlists, portfolios, journals, and provider configuration.
- FinCLI commands start with slash commands inside the TUI, for example /help, /research AAPL --quick, /macro US, /profile, /technical AAPL, and /analyze XAUUSD.
- Your role is to help users understand markets, risk, portfolio context, trading journal patterns, FinCLI commands, and general non-coding questions.
- Free chat is allowed, but you must keep your identity as FinCLI's assistant and be clear when market data is unavailable or delayed.

Financial analysis rules:
- Analyze from provided market context first. Do not invent prices, news, fundamentals, provider status, or certainty.
- If Web Research Context is provided, use it as current public context, mention source URLs, and separate sourced facts from interpretation.
- Use probabilistic language: scenario, bias, confirmation, invalidation, risk, caution.
- Do not promise profit and do not present aggressive entries as guaranteed signals.
- For technical analysis, weigh trend, momentum, volatility, support/resistance, market structure, and data quality.
- For fundamental analysis, separate valuation, growth, profitability, sector context, balance-sheet risk, and missing-data limitations.
- Always include a short non-financial-advice reminder when discussing instruments, portfolio, or trading decisions.

Coding boundary:
- Do not provide coding, debugging, refactoring, implementation plans, source code, scripts, commands for software builds, or programming architecture.
- If asked for coding help, refuse briefly and redirect to FinCLI usage, market analysis, provider setup, risk management, or journal/portfolio workflow.

Response style:
- Be concise, structured, and practical.
- Prefer bullets for market analysis.
- If the user asks casual non-market questions, answer normally while staying within the coding boundary.
""".strip()


_CODING_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(write|generate|buat|bikin|create|implement|refactor|debug|fix|compile|build)\s+(code|kode|script|program|function|fungsi|class|module|modul|app|website|backend|frontend)\b",
        r"\b(code|kode|source code|script|programming|pemrograman|debugging|traceback|stack trace)\b",
        r"\b(python|javascript|typescript|react|next\.?js|node\.?js|npm|pip|django|flask|fastapi|sql|docker|kubernetes|regex)\b",
        r"\b(git|commit|pull request|unit test|pytest|lint|ci/cd|api endpoint|sdk|library|framework)\b",
        r"\b(error di kode|bug di kode|perbaiki kode|arsitektur software|software architecture)\b",
    )
)


_SYMBOL_PATTERN = re.compile(r"\b[A-Z][A-Z0-9./:_-]{1,14}\b", re.IGNORECASE)
_MARKET_KEYWORDS = {
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "AMZN",
    "GOOGL",
    "META",
    "BTC",
    "ETH",
    "BTCUSD",
    "BTCUSDT",
    "ETHUSD",
    "ETHUSDT",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "XAUUSD",
    "XAGUSD",
    "GOLD",
    "SILVER",
    "WTI",
    "BRENT",
    "SPX",
    "SP500",
    "NASDAQ",
    "NDX",
    "DOW",
    "DAX",
    "FTSE",
    "NIKKEI",
    "HSI",
}
_SYMBOL_STOPWORDS = {
    "AI",
    "API",
    "CLI",
    "TUI",
    "FINCLI",
    "BUY",
    "SELL",
    "CAUTION",
    "RSI",
    "MACD",
    "EMA",
    "SMA",
    "ATR",
    "PE",
    "EPS",
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "IDR",
}


def is_coding_request(prompt: str) -> bool:
    """Return True when a free-chat prompt asks for programming help."""
    normalized = prompt.strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _CODING_PATTERNS)


def coding_refusal() -> str:
    """Return FinCLI-specific refusal text for coding prompts."""
    return (
        "Aku FinCLI AI Assistance untuk market, portfolio, journal, provider, dan risk workflow. "
        "Aku tidak menangani coding, debugging, refactor, atau pembuatan software di dalam FinCLI. "
        "Kamu bisa tanya analisis market, fundamental, technical setup, watchlist, portfolio, journal, "
        "atau cara memakai command FinCLI."
    )


def extract_market_symbols(prompt: str, limit: int = 3) -> list[str]:
    """Extract explicit market symbols from a user prompt."""
    found: list[str] = []
    for match in _SYMBOL_PATTERN.finditer(prompt):
        raw_symbol = match.group(0).strip(".,?!:;()[]{}")
        symbol = raw_symbol.upper()
        if symbol in _SYMBOL_STOPWORDS:
            continue
        if not raw_symbol.isupper() and symbol not in _MARKET_KEYWORDS:
            continue
        if len(symbol) <= 2 and symbol not in _MARKET_KEYWORDS:
            continue
        if symbol.isdigit():
            continue
        if symbol not in found:
            found.append(symbol)
        if len(found) >= limit:
            break
    return found


def build_fincli_assistant_prompt(user_prompt: str, market_context: str = "") -> str:
    """Build the final prompt sent to the configured AI provider."""
    context = market_context.strip() or "No explicit market context was available for this free-chat prompt."
    return (
        f"{FINCLI_ASSISTANT_SYSTEM_PROMPT}\n\n"
        "Runtime Market Context:\n"
        f"{context}\n\n"
        "User Prompt:\n"
        f"{user_prompt.strip()}\n\n"
        "Instruction:\n"
        "- Answer the user's prompt directly.\n"
        "- If market or web context is present, cite provider/data-quality limitations and source URLs when available.\n"
        "- If market context is missing and the user asks about an instrument, say what data is missing.\n"
        "- Keep the coding boundary enforced.\n"
    )


def build_web_research_answer_prompt(user_prompt: str, web_context: str) -> str:
    """Build a prompt that turns gathered web context into an answer, not a source dump."""
    context = web_context.strip() or "Web Research: no public web context returned."
    return (
        f"{FINCLI_ASSISTANT_SYSTEM_PROMPT}\n\n"
        "Web Search Skill Result:\n"
        f"{context}\n\n"
        "User Prompt:\n"
        f"{user_prompt.strip()}\n\n"
        "Instruction:\n"
        "- You already have web search context above. Do not answer by only listing articles or links.\n"
        "- Synthesize the sources into a useful explanation/summary for the user.\n"
        "- Prioritize facts found in the web context, then clearly label interpretation.\n"
        "- If sources disagree or are thin, say that the evidence is limited.\n"
        "- Use this output structure when relevant:\n"
        "  1. Ringkasan singkat\n"
        "  2. Poin utama/penyebab\n"
        "  3. Dampak atau implikasi\n"
        "  4. Risiko dan hal yang perlu diverifikasi\n"
        "  5. Sumber singkat\n"
        "- Keep source citations compact: source title or URL only where useful.\n"
        "- Do not provide financial advice or certainty about market direction.\n"
    )
