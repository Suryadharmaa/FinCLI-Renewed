"""FinCLI AI assistant prompt and safety helpers."""

from __future__ import annotations

import re

from fincli import __version__


FINCLI_ASSISTANT_SYSTEM_PROMPT = f"""
You are FinCLI AI Assistance, the embedded assistant inside FinCLI v{__version__}.

Identity and scope:
- FinCLI is a production-ready financial CLI/TUI terminal for market research, technical analysis, AI-assisted analysis, provider management, portfolio risk, journaling, watchlists, backtesting, paper trading, and local-first financial workflows.
- FinCLI commands start with slash commands inside the TUI, for example /help, /research AAPL --deep, /market AAPL 1d, /portfolio risk, /analyze XAUUSD.
- Your role is to help users understand markets, risk, portfolio context, trading journal patterns, FinCLI commands and features, and general non-coding questions.
- Free chat is allowed, but you must keep your identity as FinCLI's assistant and be clear when market data is unavailable or delayed.
- When user asks how to use FinCLI, reference specific commands with examples from the Command Reference below.

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
        "I'm FinCLI AI Assistance for market, portfolio, journal, provider, and risk workflow. "
        "I don't handle coding, debugging, refactoring, or software creation within FinCLI. "
        "You can ask about market analysis, fundamental/technical setup, watchlist, portfolio, journal, "
        "or how to use FinCLI commands."
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


def build_command_reference() -> str:
    """Build a structured command reference from the command registry."""
    from fincli import __version__
    from fincli.app.cli.commands import COMMANDS

    groups: dict[str, list[str]] = {}
    for cmd in COMMANDS:
        group = cmd.group or "General"
        groups.setdefault(group, []).append(f"  {cmd.name} — {cmd.description}\n    Example: {cmd.example}")

    lines = [f"FinCLI v{__version__} Command Reference:\n"]
    for group_name in sorted(groups):
        lines.append(f"\n[{group_name}]")
        lines.extend(groups[group_name])
    return "\n".join(lines)


def build_fincli_feature_context() -> str:
    """Build a summary of FinCLI features for the assistant context."""
    from fincli import __version__
    return f"""FinCLI v{__version__} Features:

Research & Analysis:
- Research Engine v3: /research with --snapshot (default), --deep (AI-powered), --report modes. Source-aware output with trust gate, data quality scoring, cited sources.
- Multi-timeframe analysis: /mtf AAPL 1d,1h,15m for alignment across timeframes.
- Technical analysis: RSI, MACD, EMA/SMA, Bollinger Bands, ATR, support/resistance, market structure via /technical and /analyze.
- Technical debate: AI-powered bull/bear debate on instruments.
- Backtesting: /backtest with fees, slippage, walk-forward, position sizing, Monte Carlo, export.

Provider System v2:
- Formal capability declarations, ProviderResponse envelope with quality scoring (0-100).
- Per-operation metrics, circuit breaker with visibility and manual reset via /provider reset.
- Market providers: yfinance (default delayed fallback), Finnhub, Twelve Data, Alpha Vantage, custom providers.
- AI providers: OpenRouter, OpenAI, Groq, Together, HuggingFace, Gemini, Anthropic.
- 100+ news connector catalog with free RSS fallbacks.

Portfolio & Risk:
- Portfolio Risk v3: exposure by asset class, currency exposure, concentration risk, drawdown estimate, risk budget, PnL, health score.
- Portfolio commands: add, remove, update (DCA), performance, chart, snapshot, history, what-if analysis, benchmark comparison.
- Transaction ledger: /tx add buy/sell for trade tracking.

Trading Safety Layer:
- Risk guard, immutable audit log, paper trading, 3 algo strategies.
- Kill switch (/trading kill, /trading resume), position management, broker sandbox adapters.
- Realtime streaming connectors (Kraken, HyperLiquid, equity polling).

Workflow:
- Watchlist: add, remove, list by group, notes, /scan with indicator filters.
- Journal: add, edit, delete, stats, AI review of trading habits.
- Alerts: price/RSI/volume/MACD alerts, background daemon, history.
- Session history: browse, resume, save, export.

System:
- Theme system: 7 presets, custom themes (create, import, export).
- Plugin system with manifest validation, sandbox, lifecycle hooks.
- Security: encrypted secrets at rest, token pattern scanning, input validation, /security scan.
- Error classification, crash context, /doctor report for diagnostics.
- Local-first storage: SQLite database, encrypted secrets, cache, sessions, audit log.
- Export: journal, portfolio, alerts to CSV/JSON.
- Economic calendar with provider fallback.
- Tutorial system for beginners: /tutorial."""


class ConversationHistory:
    """Manages conversation context for AI assistant with token-based sliding window.

    Uses character count estimation (~4 chars/token) to stay within budget.
    Default max_tokens=4000 (~16000 chars) balances context richness vs cost.
    """

    # Approximation: 1 token ≈ 4 characters (English/Indonesian average)
    CHARS_PER_TOKEN = 4

    def __init__(self, max_tokens: int = 4000, max_turns: int = 20) -> None:
        self._history: list[dict[str, str]] = []
        self._max_tokens = max_tokens
        self._max_turns = max_turns

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count from character count."""
        return len(text) // self.CHARS_PER_TOKEN

    def _turn_tokens(self, turn: dict[str, str]) -> int:
        """Estimate tokens for a single conversation turn."""
        text = f"User: {turn['user']}"
        if turn["assistant"]:
            text += f"\nAssistant: {turn['assistant']}"
        return self._estimate_tokens(text)

    def _total_tokens(self) -> int:
        """Estimate total tokens in history."""
        return sum(self._turn_tokens(t) for t in self._history)

    def add(self, user_prompt: str, response_summary: str = "") -> None:
        """Add a conversation turn, evicting oldest if token budget exceeded."""
        self._history.append({
            "user": user_prompt.strip(),
            "assistant": response_summary.strip()[:500] if response_summary else "",
        })

        # Enforce hard turn limit
        if len(self._history) > self._max_turns:
            self._history = self._history[-self._max_turns:]

        # Sliding window: evict oldest turns until within token budget
        while self._total_tokens() > self._max_tokens and len(self._history) > 1:
            self._history.pop(0)

    def get_context(self) -> str:
        """Get conversation history as context string."""
        if not self._history:
            return ""
        lines = ["Recent conversation:"]
        for i, turn in enumerate(self._history, 1):
            lines.append(f"  {i}. User: {turn['user']}")
            if turn["assistant"]:
                lines.append(f"     Assistant: {turn['assistant']}")
        return "\n".join(lines)

    def clear(self) -> None:
        """Clear conversation history."""
        self._history.clear()

    @property
    def length(self) -> int:
        return len(self._history)

    @property
    def estimated_tokens(self) -> int:
        """Current estimated token usage."""
        return self._total_tokens()

    @property
    def token_budget(self) -> int:
        """Maximum token budget."""
        return self._max_tokens


# Global conversation history instance (4k token window)
_conversation_history = ConversationHistory(max_tokens=4000)


def get_conversation_history() -> ConversationHistory:
    """Get the global conversation history instance."""
    return _conversation_history


def build_fincli_assistant_prompt(
    user_prompt: str,
    market_context: str = "",
    conversation_history: ConversationHistory | None = None,
) -> str:
    """Build the final prompt sent to the configured AI provider."""
    context = market_context.strip() or "No explicit market context was available for this free-chat prompt."
    command_ref = build_command_reference()
    feature_ctx = build_fincli_feature_context()

    # Add conversation context if available
    history = conversation_history or _conversation_history
    history_context = history.get_context()
    history_section = f"\n{history_context}\n" if history_context else ""

    return (
        f"{FINCLI_ASSISTANT_SYSTEM_PROMPT}\n\n"
        f"{feature_ctx}\n\n"
        f"{command_ref}\n\n"
        "Runtime Market Context:\n"
        f"{context}\n\n"
        f"{history_section}"
        "User Prompt:\n"
        f"{user_prompt.strip()}\n\n"
        "Instruction:\n"
        "- Answer the user's prompt directly.\n"
        "- If user asks about FinCLI usage, reference specific commands from the Command Reference above.\n"
        "- If market or web context is present, cite provider/data-quality limitations and source URLs when available.\n"
        "- If market context is missing and the user asks about an instrument, say what data is missing.\n"
        "- If there is recent conversation context, use it to provide more relevant answers.\n"
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
