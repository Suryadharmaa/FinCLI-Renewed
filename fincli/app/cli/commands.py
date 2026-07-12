"""Slash command registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    description: str
    example: str
    group: str = "General"


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("/help", "Show help, command list, and examples.", "/help"),
    CommandSpec("/dashboard", "Show compact FinCLI dashboard.", "/dashboard", "General"),
    CommandSpec("/ai_model", "Interactive AI provider/model picker. No arguments: open picker.", "/ai_model", "AI"),
    CommandSpec("/news_model", "Interactive market/news provider picker. No arguments: open picker.", "/news_model", "Provider"),
    CommandSpec("/news_model list", "Show 100+ news connectors and access status.", "/news_model list", "Provider"),
    CommandSpec("/news_model search", "Search news connectors.", "/news_model search rss", "Provider"),
    CommandSpec("/news_model use", "Select primary news provider.", "/news_model use google_news_rss", "Provider"),
    CommandSpec("/news_model priority", "Set fallback news provider order.", "/news_model priority google_news_rss,yfinance,marketaux", "Provider"),
    CommandSpec("/symbol", "Search and resolve symbols across providers.", "/symbol search BBRI", "Market"),
    CommandSpec("/symbol resolve", "Normalize symbol per provider.", "/symbol resolve XAUUSD --asset commodity", "Market"),
    CommandSpec("/research", "Research Engine v3: snapshot/deep/report with sources, sector/macro/news blending, and export.", "/research AAPL --deep", "Research"),
    CommandSpec("/macro", "Macro fallback dashboard and connector-ready context.", "/macro Indonesia", "Research"),
    CommandSpec("/profile", "Show profile and gameplay risk settings.", "/profile", "Profile"),
    CommandSpec("/profile set", "Save gameplay profile.", '/profile set "Budi" 350 USD 1:100 1.5', "Profile"),
    CommandSpec("/doctor", "Check config, provider, database, and core command health.", "/doctor", "System"),
    CommandSpec("/doctor report", "Generate diagnostic report (no secrets).", "/doctor report", "System"),
    CommandSpec("/setup", "Setup wizard — check config and setup guide.", "/setup", "System"),
    CommandSpec("/setup check", "Check current config details.", "/setup check", "System"),
    CommandSpec("/setup keys", "API keys setup guide.", "/setup keys", "System"),
    CommandSpec("/setup profile", "Check/setup user profile.", "/setup profile", "System"),
    CommandSpec("/setup theme", "Theme setup guide.", "/setup theme", "System"),
    CommandSpec("/secrets status", "Audit local secret status without showing values.", "/secrets status", "Security"),
    CommandSpec("/secrets clear", "Clear all local API keys from secret store.", "/secrets clear", "Security"),
    CommandSpec("/security status", "Show security status: secrets, redaction, validation, rate limiting.", "/security status", "Security"),
    CommandSpec("/security audit", "Show security audit log events (immutable).", "/security audit", "Security"),
    CommandSpec("/security scan", "Scan for exposed secrets and security issues.", "/security scan", "Security"),
    CommandSpec("/security lockdown", "Emergency: clear all secrets and disable providers.", "/security lockdown", "Security"),
    CommandSpec("/security purge", "Clear secrets, session history, and local cache.", "/security purge", "Security"),
    CommandSpec("/security session", "Show session security status.", "/security session", "Security"),
    CommandSpec("/notification", "Manage webhook notifications (Discord/Telegram).", "/notification", "System"),
    CommandSpec("/notification add", "Add webhook target.", "/notification add discord alerts https://discord.com/api/webhooks/...", "System"),
    CommandSpec("/notification test", "Test webhook notification.", "/notification test discord:alerts", "System"),
    CommandSpec("/notification remove", "Remove webhook target.", "/notification remove discord:alerts", "System"),
    CommandSpec("/agent", "View FinCLI agent framework.", "/agent list", "AI"),
    CommandSpec("/agent show", "Show agent framework details.", "/agent show buffett", "AI"),
    CommandSpec("/connector", "View data connector catalog.", "/connector list macro", "Provider"),
    CommandSpec("/connector search", "Search data connectors.", "/connector search yahoo", "Provider"),
    CommandSpec("/plugin", "Show local FinCLI plugins.", "/plugin list", "System"),
    CommandSpec("/plugin status", "Check local plugin manifest status.", "/plugin status", "System"),
    CommandSpec("/plugin validate", "Validate local plugin manifests.", "/plugin validate", "System"),
    CommandSpec("/market", "Professional market overview for an instrument.", "/market AAPL 1d", "Market"),
    CommandSpec("/news", "Show latest news/fundamentals for an instrument.", "/news AAPL", "Market"),
    CommandSpec("/technical", "Technical analysis for an instrument.", "/technical BTC-USD 1d", "Analysis"),
    CommandSpec("/chart", "ASCII candlestick chart with RSI/MACD overlays.", "/chart AAPL 1d --overlay rsi,macd", "Analysis"),
    CommandSpec("/mtf", "Multi-timeframe technical alignment.", "/mtf AAPL 1d,1h,15m", "Analysis"),
    CommandSpec("/backtest", "Professional backtest: fees, slippage, ratios, Monte Carlo, walk-forward, export.", "/backtest AAPL sma_cross 1d --monte-carlo", "Analysis"),
    CommandSpec("/trading", "Trading layer: risk guard, broker catalog, paper trading, audit.", "/trading", "Trading"),
    CommandSpec("/trading kill", "Activate kill switch to block all paper orders.", "/trading kill", "Trading"),
    CommandSpec("/trading resume", "Deactivate kill switch and re-enable paper orders.", "/trading resume", "Trading"),
    CommandSpec("/trading risk", "Show risk guard status, daily PnL, and configuration.", "/trading risk", "Trading"),
    CommandSpec("/trading audit", "Show order audit log (immutable).", "/trading audit", "Trading"),
    CommandSpec("/trading cancel", "Cancel a queued paper order.", "/trading cancel 5", "Trading"),
    CommandSpec("/trading positions", "Show aggregated paper trading positions.", "/trading positions", "Trading"),
    CommandSpec("/trading broker use", "Activate broker sandbox adapter.", "/trading broker use Alpaca", "Trading"),
    CommandSpec("/trading broker status", "Show broker adapter status.", "/trading broker status", "Trading"),
    CommandSpec("/trading stream", "Show realtime connector stream status.", "/trading stream", "Trading"),
    CommandSpec("/trading live status", "Show live trading broker connection status.", "/trading live status", "Trading"),
    CommandSpec("/trading live connect", "Connect to broker for live/paper trading.", "/trading live connect alpaca paper", "Trading"),
    CommandSpec("/trading live disconnect", "Disconnect from broker.", "/trading live disconnect", "Trading"),
    CommandSpec("/trading live buy", "Place LIVE buy order (with confirmation).", "/trading live buy AAPL 10 --confirm", "Trading"),
    CommandSpec("/trading live sell", "Place LIVE sell order (with confirmation).", "/trading live sell AAPL 5 --confirm", "Trading"),
    CommandSpec("/trading live positions", "Show positions from broker.", "/trading live positions", "Trading"),
    CommandSpec("/trading live orders", "Show order history from broker.", "/trading live orders", "Trading"),
    CommandSpec("/trading live account", "Show broker account info.", "/trading live account", "Trading"),
    CommandSpec("/yahoo", "Show Yahoo Finance table for history/statistics/profile/financials/analysis/holders.", "/yahoo BBRI statistics", "Market"),
    CommandSpec("/web", "Show local web access status and quick actions.", "/web status", "System"),
    CommandSpec("/web start", "Start the authenticated local web UI.", "/web start", "System"),
    CommandSpec("/web stop", "Stop the local web UI.", "/web stop", "System"),
    CommandSpec("/web open", "Open the local web UI in a browser.", "/web open", "System"),
    CommandSpec("/web token rotate", "Rotate the local web access token.", "/web token rotate", "Security"),
    CommandSpec("/web config", "Show or update local web settings.", "/web config set port 19850", "System"),
    CommandSpec("/web research", "Run a public-source research query.", "/web why is rupiah weakening", "Advanced"),
    CommandSpec("/ai", "Free chat with AI assistant. No arguments: show status.", "/ai summarize AAPL risk", "AI"),
    CommandSpec("/analyze", "AI analyzes instrument market structure.", "/analyze ETH-USD 4h", "Analysis"),
    CommandSpec("/watchlist", "Show watchlist.", "/watchlist", "Watchlist"),
    CommandSpec("/watchlist add", "Add instrument to watchlist.", "/watchlist add AAPL crypto \"breakout setup\"", "Watchlist"),
    CommandSpec("/watchlist remove", "Remove instrument from watchlist.", "/watchlist remove AAPL", "Watchlist"),
    CommandSpec("/watchlist list", "Show watchlist, filter by group.", "/watchlist list crypto", "Watchlist"),
    CommandSpec("/watchlist note", "Add/update note for watchlist instrument.", "/watchlist note AAPL \"breakout setup\"", "Watchlist"),
    CommandSpec("/watchlist groups", "Show watchlist group list.", "/watchlist groups", "Watchlist"),
    CommandSpec("/portfolio", "Show active portfolio.", "/portfolio", "Portfolio"),
    CommandSpec("/portfolio portfolios", "List all portfolios.", "/portfolio portfolios", "Portfolio"),
    CommandSpec("/portfolio create", "Create new portfolio.", "/portfolio create crypto \"Crypto holdings\"", "Portfolio"),
    CommandSpec("/portfolio switch", "Switch to another portfolio.", "/portfolio switch crypto", "Portfolio"),
    CommandSpec("/portfolio compare", "Compare two portfolios.", "/portfolio compare crypto", "Portfolio"),
    CommandSpec("/portfolio delete", "Delete portfolio.", "/portfolio delete crypto", "Portfolio"),
    CommandSpec("/portfolio add", "Add position/asset.", "/portfolio add BTC-USD 0.05 65000", "Portfolio"),
    CommandSpec("/portfolio remove", "Remove position/asset.", "/portfolio remove BTC-USD", "Portfolio"),
    CommandSpec("/portfolio update", "DCA: add position with weighted average.", "/portfolio update AAPL 5 160", "Portfolio"),
    CommandSpec("/portfolio performance", "Show portfolio performance.", "/portfolio performance", "Portfolio"),
    CommandSpec("/portfolio risk", "Portfolio Risk v3: exposure, concentration, PnL, health score, risk ratios.", "/portfolio risk", "Portfolio"),
    CommandSpec("/portfolio chart", "Portfolio performance chart with risk ratios (Sharpe/Sortino/Calmar).", "/portfolio chart", "Portfolio"),
    CommandSpec("/portfolio snapshot", "Save portfolio snapshot for time-series tracking.", "/portfolio snapshot", "Portfolio"),
    CommandSpec("/portfolio history", "Show portfolio snapshot history.", "/portfolio history", "Portfolio"),
    CommandSpec("/portfolio whatif", "What-if analysis: add/remove positions, see impact before commit.", "/portfolio whatif add AAPL 10 200", "Portfolio"),
    CommandSpec("/portfolio benchmark", "Compare portfolio vs benchmark (SPY, QQQ, BTC, etc).", "/portfolio benchmark SPY", "Portfolio"),
    CommandSpec("/portfolio rebalance", "Suggest rebalancing trades based on target allocation.", "/portfolio rebalance", "Portfolio"),
    CommandSpec("/tx", "Show transaction ledger.", "/tx list", "Portfolio"),
    CommandSpec("/tx add", "Add buy/sell transaction.", "/tx add buy AAPL 10 185", "Portfolio"),
    CommandSpec("/journal", "Show trading/investment journal.", "/journal", "Journal"),
    CommandSpec("/journal add", "Add short journal entry.", '/journal add BTC-USD bullish "Breakout failed, wait for confirmation"', "Journal"),
    CommandSpec("/journal edit", "Edit journal entry field.", "/journal edit 1 --bias bearish --result loss", "Journal"),
    CommandSpec("/journal delete", "Delete journal entry.", "/journal delete 1", "Journal"),
    CommandSpec("/journal show", "Show journal entry details.", "/journal show 1", "Journal"),
    CommandSpec("/journal stats", "Show journal statistics.", "/journal stats", "Journal"),
    CommandSpec("/journal review", "AI review of journal habits.", "/journal review", "Journal"),
    CommandSpec("/alert", "Show local price alerts.", "/alert", "Alert"),
    CommandSpec("/alert add", "Add alert (price/RSI/volume/MACD).", "/alert add AAPL above 200", "Alert"),
    CommandSpec("/alert check", "Check active alerts using quote provider.", "/alert check", "Alert"),
    CommandSpec("/alert history", "Show triggered alert history.", "/alert history", "Alert"),
    CommandSpec("/alert daemon", "Start/stop/status background alert checker.", "/alert daemon start", "Alert"),
    CommandSpec("/history", "Session picker — view and resume previous sessions.", "/history", "History"),
    CommandSpec("/history resume", "Resume last or specific session.", "/history resume <#|session_id>", "History"),
    CommandSpec("/history current", "Show current session command history.", "/history current", "History"),
    CommandSpec("/history show", "Show specific session details.", "/history show <session_id>", "History"),
    CommandSpec("/history save", "Name the current session.", '/history save "Morning IHSG research"', "History"),
    CommandSpec("/history delete", "Delete specific session.", "/history delete <session_id>", "History"),
    CommandSpec("/history clear", "Clear all session history.", "/history clear", "History"),
    CommandSpec("/session save", "Save current session state.", "/session save", "History"),
    CommandSpec("/session restore", "Restore state from previous session.", "/session restore", "History"),
    CommandSpec("/session status", "Show session state status.", "/session status", "History"),
    CommandSpec("/config", "Show active config without exposing API keys.", "/config"),
    CommandSpec("/theme", "Show active theme and available themes.", "/theme", "Theme"),
    CommandSpec("/theme list", "Show all themes with color preview.", "/theme list", "Theme"),
    CommandSpec("/theme create", "Create custom theme from base theme.", "/theme create mytheme --base midnight", "Theme"),
    CommandSpec("/theme import", "Import theme from JSON file.", "/theme import theme.json", "Theme"),
    CommandSpec("/theme export", "Export theme to JSON file.", "/theme export midnight theme.json", "Theme"),
    CommandSpec("/scan", "Watchlist/market scanner with indicator filters.", "/scan sp500 rsi<30 --limit 20", "Market"),
    CommandSpec("/scan export", "Export scanner results to CSV/JSON.", "/scan export csv scan.csv rsi<30 1d", "Market"),
    CommandSpec("/report market", "Export market report to Markdown/JSON.", "/report market AAPL md report.md", "Export"),
    CommandSpec("/calendar", "Economic calendar provider/fallback.", "/calendar week US high", "Market"),
    CommandSpec("/calendar export", "Export economic calendar to CSV/JSON.", "/calendar export csv calendar.csv week US high", "Market"),
    CommandSpec("/provider status", "Show active provider status.", "/provider status", "Provider"),
    CommandSpec("/provider metrics", "Show active provider runtime metrics.", "/provider metrics", "Provider"),
    CommandSpec("/provider trust", "Show provider trust, fallback, and AI confidence limits.", "/provider trust", "Provider"),
    CommandSpec("/provider list", "Show all available market providers.", "/provider list", "Provider"),
    CommandSpec("/provider capabilities", "Show capability matrix per provider and command.", "/provider capabilities", "Provider"),
    CommandSpec("/provider reset", "Reset provider circuit breaker.", "/provider reset finnhub", "Provider"),
    CommandSpec("/provider key rotate", "Check/rotate provider API key.", "/provider key rotate finnhub", "Provider"),
    CommandSpec("/provider entitlement", "Show provider capability and realtime/delayed label.", "/provider entitlement", "Provider"),
    CommandSpec("/provider test", "Test active provider quote for symbol.", "/provider test AAPL", "Provider"),
    CommandSpec("/provider key status", "Show market provider API key status.", "/provider key status", "Provider"),
    CommandSpec("/cache stats", "Show persistent market cache statistics.", "/cache stats", "System"),
    CommandSpec("/cache clear", "Clear runtime and persistent market cache.", "/cache clear", "System"),
    CommandSpec("/export journal", "Export journal to CSV/JSON.", "/export journal csv journal.csv", "Export"),
    CommandSpec("/export portfolio", "Export portfolio to CSV/JSON.", "/export portfolio json portfolio.json", "Export"),
    CommandSpec("/export alerts", "Export alert history to CSV/JSON.", "/export alerts csv alerts.csv", "Export"),
    CommandSpec("/export all", "Batch export all data (portfolio, journal, alerts, trades).", "/export all json ./exports", "Export"),
    CommandSpec("/export broker", "Export live trading history from broker.", "/export broker csv broker_trades.csv", "Export"),
    CommandSpec("/tutorial", "Interactive tutorial for beginners. Type /tutorial to start.", "/tutorial", "General"),
    CommandSpec("/tutorial next", "Go to next lesson.", "/tutorial next", "General"),
    CommandSpec("/tutorial reset", "Reset tutorial progress.", "/tutorial reset", "General"),
    CommandSpec("/clear", "Clear terminal output.", "/clear"),
    CommandSpec("/exit", "Exit the application.", "/exit"),
    CommandSpec("/lang", "Change display language (en/id).", "/lang id", "General"),
)


class CommandRegistry:
    """Lookup and autocomplete slash commands."""

    def __init__(self, commands: tuple[CommandSpec, ...] = COMMANDS) -> None:
        self.commands = commands

    def suggest(self, query: str, limit: int = 8) -> list[CommandSpec]:
        normalized = query.strip().lower()
        if not normalized:
            return list(self.commands[:limit])
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"

        exact = [cmd for cmd in self.commands if cmd.name.lower().startswith(normalized)]
        fuzzy = [cmd for cmd in self.commands if normalized.replace("/", "") in cmd.name.lower().replace("/", "")]
        seen: set[str] = set()
        merged: list[CommandSpec] = []
        for cmd in [*exact, *fuzzy]:
            if cmd.name not in seen:
                seen.add(cmd.name)
                merged.append(cmd)
        return merged[:limit]

    def all(self) -> tuple[CommandSpec, ...]:
        return self.commands
