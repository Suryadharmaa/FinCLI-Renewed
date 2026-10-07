"""Command parsing and routing."""

from __future__ import annotations

import logging

import httpx
from rich.panel import Panel
from rich.table import Table

from fincli.app.cli.handlers.common import (
    _fmt,
    _fmt_pct,
    _format_ai_response,
    _format_benchmark,
    _format_correlation_matrix,
    _format_journal_stats,
    _format_portfolio_chart,
    _format_portfolio_risk,
    _format_portfolio_tax,
    _format_rebalance,
    _format_transactions,
    _format_whatif,
)
from fincli.app.cli.result import CommandResult
from fincli.app.modules.journal_analytics import build_journal_review_prompt, calculate_journal_stats
from fincli.app.modules.portfolio_risk import PortfolioRiskReport, build_portfolio_risk
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.utils.errors import CommandError, FinCLIError, ProviderError
from fincli.app.utils.formatting import MarkdownBlock

logger = logging.getLogger(__name__)

# Constants
PROVIDER_TIMEOUT_BUFFER_SECONDS = 15.0


class PortfolioCommands:
    """Portfolio command handlers."""

    def _watchlist(self, args: list[str]) -> CommandResult:
        if not args:
            return self._watchlist_table()

        action = args[0].lower()

        if action == "add" and len(args) >= 2:
            group = args[2] if len(args) >= 3 else "default"
            notes = args[3] if len(args) >= 4 else ""
            self.watchlist.add(args[1], group_name=group, notes=notes)
            return CommandResult(Panel(f"{args[1].upper()} added to watchlist (group: {group}).", title="Watchlist"))
        if action == "remove" and len(args) >= 2:
            self.watchlist.remove(args[1])
            return CommandResult(Panel(f"{args[1].upper()} removed from watchlist.", title="Watchlist"))
        if action == "list":
            group = args[1] if len(args) >= 2 else None
            return self._watchlist_table(group)
        if action == "note" and len(args) >= 3:
            self.watchlist.update_notes(args[1], " ".join(args[2:]))
            return CommandResult(Panel(f"Note for {args[1].upper()} saved.", title="Watchlist"))
        if action == "groups":
            groups = self.watchlist.groups()
            if not groups:
                return CommandResult(Panel("No groups yet.", title="Watchlist Groups"))
            table = Table(title="Watchlist Groups", expand=True)
            table.add_column("Group", style="cyan")
            table.add_column("Count", justify="right")
            for g in groups:
                rows = self.watchlist.list(g)
                table.add_row(g, str(len(rows)))
            return CommandResult(table)

        # If arg looks like a group name, filter by it
        if len(args) == 1:
            rows = self.watchlist.list(args[0])
            if rows:
                return self._watchlist_table(args[0])

        raise CommandError(
            "Format: /watchlist, /watchlist add <symbol> [group] [notes], /watchlist remove <symbol>, /watchlist list [group], /watchlist note <symbol> <text>, /watchlist groups"
        )

    def _watchlist_table(self, group: str | None = None) -> CommandResult:
        rows = self.watchlist.list(group)
        title = f"Watchlist | {group}" if group else "Watchlist"
        table = Table(title=title, expand=True)
        table.add_column("Symbol", style="cyan")
        table.add_column("Price", justify="right")
        table.add_column("Currency")
        table.add_column("Status")
        table.add_column("Group")
        table.add_column("Notes")
        table.add_column("Created")
        for row in rows:
            quote = self._safe_quote(str(row["symbol"]))
            table.add_row(
                str(row["symbol"]),
                _fmt(quote.price) if quote else "N/A",
                quote.currency if quote else "-",
                quote.status if quote else "unavailable",
                str(row["group_name"]),
                str(row.get("notes", "") or "")[:30],
                str(row["created_at"]),
            )
        if not rows:
            table.add_row("-", "-", "-", "-", "-", "No data yet. Use /watchlist add AAPL", "-")
        return CommandResult(table)

    def _favourites(self, args: list[str]) -> CommandResult:
        if not args:
            return self._favourites_list()

        action = args[0].lower()
        if action == "add" and len(args) >= 2:
            symbol = args[1].upper()
            self.db.execute(
                "INSERT OR REPLACE INTO favourites (symbol, last_used, use_count) VALUES (?, CURRENT_TIMESTAMP, COALESCE((SELECT use_count FROM favourites WHERE symbol = ?) + 1, 1))",
                (symbol, symbol),
            )
            return CommandResult(Panel(f"{symbol} added to favourites.", title="Favourites", border_style="green"))
        if action == "remove" and len(args) >= 2:
            symbol = args[1].upper()
            self.db.execute("DELETE FROM favourites WHERE symbol = ?", (symbol,))
            return CommandResult(Panel(f"{symbol} removed from favourites.", title="Favourites"))
        if action == "list":
            return self._favourites_list()

        raise CommandError(
            "Format: /favourites, /favourites add <symbol>, /favourites remove <symbol>, /favourites list"
        )

    def _favourites_list(self) -> CommandResult:
        rows = self.db.query("SELECT symbol, last_used, use_count FROM favourites ORDER BY use_count DESC LIMIT 20")
        table = Table(title="Favourites | Quick Access", expand=True)
        table.add_column("Symbol", style="cyan")
        table.add_column("Price", justify="right")
        table.add_column("Currency")
        table.add_column("Status")
        table.add_column("Used", justify="right")
        table.add_column("Last Used")
        for row in rows:
            quote = self._safe_quote(str(row["symbol"]))
            table.add_row(
                str(row["symbol"]),
                _fmt(quote.price) if quote else "N/A",
                quote.currency if quote else "-",
                quote.status if quote else "unavailable",
                str(row["use_count"]),
                str(row["last_used"]),
            )
        if not rows:
            table.add_row("-", "-", "-", "-", "-", "No favourites yet. Use /favourites add AAPL")
        table.caption = "Frequently used symbols. Use /favourites add <symbol> to track."
        return CommandResult(table)

    def _portfolio(self, args: list[str]) -> CommandResult:
        # Multi-portfolio subcommands
        if args and args[0].lower() == "create":
            if len(args) < 2:
                raise CommandError("Format: /portfolio create <name> [description]")
            name = args[1].lower()
            desc = " ".join(args[2:]) if len(args) > 2 else ""
            self.portfolio.create(name, desc)
            return CommandResult(Panel(f"Portfolio '{name}' created.", title="Portfolio", border_style="green"))

        if args and args[0].lower() == "switch":
            if len(args) < 2:
                raise CommandError("Format: /portfolio switch <name>")
            name = args[1].lower()
            portfolios = self.portfolio.list_portfolios()
            names = {str(p["name"]) for p in portfolios}
            if name not in names:
                raise CommandError(f"Portfolio '{name}' not found. Create with /portfolio create {name}")
            self.portfolio.set_portfolio(name)
            return CommandResult(Panel(f"Active portfolio: {name}", title="Portfolio", border_style="green"))

        if args and args[0].lower() == "delete":
            if len(args) < 2:
                raise CommandError("Format: /portfolio delete <name>")
            name = args[1].lower()
            if name == "main":
                raise CommandError("Cannot delete 'main' portfolio.")
            if self.portfolio.delete(name):
                if self.portfolio.portfolio_name == name:
                    self.portfolio.set_portfolio("main")
                return CommandResult(Panel(f"Portfolio '{name}' deleted.", title="Portfolio", border_style="green"))
            return CommandResult(Panel(f"Portfolio '{name}' not found.", title="Portfolio", border_style="yellow"))

        if args and args[0].lower() == "portfolios":
            portfolios = self.portfolio.list_portfolios()
            table = Table(title="Portfolios", expand=True)
            table.add_column("Name", style="cyan")
            table.add_column("Description")
            table.add_column("Active")
            table.add_column("Created")
            for p in portfolios:
                is_active = "●" if str(p["name"]) == self.portfolio.portfolio_name else ""
                table.add_row(str(p["name"]), str(p["description"]), is_active, str(p["created_at"]))
            return CommandResult(table)

        if args and args[0].lower() == "compare":
            if len(args) < 2:
                raise CommandError("Format: /portfolio compare <other_portfolio>")
            other = args[1].lower()
            comparison = self.portfolio.compare(other)
            table = Table(title=f"Compare: {self.portfolio.portfolio_name} vs {other}", expand=True)
            table.add_column("Portfolio", style="cyan")
            table.add_column("Symbol")
            table.add_column("Qty", justify="right")
            table.add_column("Avg Price", justify="right")
            for pname, positions in comparison.items():
                for pos in positions:
                    table.add_row(
                        pname,
                        str(pos["symbol"]),
                        f"{float(pos['quantity']):,.8g}",
                        f"{float(pos['average_price']):,.4f}",
                    )
                if not positions:
                    table.add_row(pname, "(empty)", "-", "-")
            return CommandResult(table)

        if not args:
            rows = self.portfolio.list()
            table = Table(title=f"Portfolio: {self.portfolio.portfolio_name}", expand=True)
            table.add_column("Symbol", style="cyan")
            table.add_column("Qty", justify="right")
            table.add_column("Avg Price", justify="right")
            table.add_column("Current", justify="right")
            table.add_column("PnL", justify="right")
            table.add_column("PnL %", justify="right")
            table.add_column("Currency")
            table.add_column("Updated")
            for row in rows:
                current_price, pnl, pnl_percent = self._portfolio_market_values(row)
                table.add_row(
                    str(row["symbol"]),
                    f"{float(row['quantity']):,.8g}",
                    f"{float(row['average_price']):,.4f}",
                    _fmt(current_price),
                    _fmt(pnl),
                    _fmt_pct(pnl_percent),
                    str(row["currency"]),
                    str(row["updated_at"]),
                )
            if not rows:
                table.add_row(
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                    "No positions yet. Use /portfolio add BTC-USD 0.05 65000",
                )
            return CommandResult(table)

        action = args[0].lower()
        if action == "risk":
            return CommandResult(_format_portfolio_risk(self._portfolio_risk_report()))
        if action == "correlation":
            return self._portfolio_correlation()
        if action == "tax":
            return self._portfolio_tax()
        if action == "performance":
            return CommandResult(self._portfolio_performance_table())
        if action == "chart":
            return self._portfolio_chart()
        if action == "whatif":
            return self._portfolio_whatif(args[1:])
        if action == "benchmark":
            return self._portfolio_benchmark(args[1:])
        if action == "rebalance":
            return self._portfolio_rebalance()
        if action == "snapshot":
            return self._portfolio_snapshot()
        if action == "history":
            return self._portfolio_history()
        if action == "add" and len(args) >= 4:
            try:
                quantity = float(args[2])
                average_price = float(args[3])
            except ValueError as exc:
                raise CommandError("Quantity and average price must be numbers.") from exc
            self.portfolio.add(args[1], quantity, average_price, args[4] if len(args) >= 5 else "USD")
            return CommandResult(Panel(f"Position {args[1].upper()} saved.", title="Portfolio"))
        if action == "remove" and len(args) >= 2:
            self.portfolio.remove(args[1])
            return CommandResult(Panel(f"Position {args[1].upper()} removed.", title="Portfolio"))
        if action == "update" and len(args) >= 4:
            try:
                quantity = float(args[2])
                price = float(args[3])
            except ValueError as exc:
                raise CommandError("Quantity and price must be numbers.") from exc
            result = self.portfolio.update(args[1], quantity, price, args[4] if len(args) >= 5 else "USD")
            sym = str(result["symbol"])
            act = str(result["action"])
            if act == "closed":
                msg = f"Position {sym} closed (qty = 0)."
            elif act == "updated":
                msg = f"{sym} DCA: qty {result['old_quantity']} → {result['quantity']}, avg {result['old_average_price']:.4f} → {result['average_price']:.4f}"
            else:
                msg = f"Position {sym} created: qty {result['quantity']}, avg {result['average_price']:.4f}"
            return CommandResult(Panel(msg, title="Portfolio DCA"))
        raise CommandError(
            "Format: /portfolio, /portfolio risk, /portfolio correlation, /portfolio tax, /portfolio performance, "
            "/portfolio add <symbol> <qty> <avg_price>, /portfolio update <symbol> <qty> <price>, /portfolio remove <symbol>"
        )

    def _tx(self, args: list[str]) -> CommandResult:
        if not args or args[0].lower() == "list":
            return CommandResult(_format_transactions(self.transactions.list()))

        if args[0].lower() == "add":
            if len(args) < 5:
                raise CommandError("Format: /tx add <buy|sell> <symbol> <qty> <price> [currency]")
            try:
                quantity = float(args[3])
                price = float(args[4])
            except ValueError as exc:
                raise CommandError("Quantity and price must be numbers.") from exc
            tx = self.transactions.add(
                action=args[1],
                symbol=args[2],
                quantity=quantity,
                price=price,
                currency=args[5] if len(args) >= 6 else "USD",
            )
            return CommandResult(
                Panel(
                    (
                        f"Transaction saved: {tx['action']} {tx['symbol']} "
                        f"{_fmt(float(tx['quantity']))} @ {_fmt(float(tx['price']))} "
                        f"| Realized PnL {_fmt(float(tx['realized_pnl']))}"
                    ),
                    title="Transaction",
                    border_style="green",
                )
            )

        raise CommandError("Format: /tx add <buy|sell> <symbol> <qty> <price> [currency] or /tx list")

    def _journal(self, args: list[str]) -> CommandResult:
        if not args:
            rows = self.journal.list()
            return CommandResult(self._journal_table(rows, "Journal"))

        action = args[0].lower()

        if action == "stats":
            rows = self.journal.list(limit=10_000)
            stats = calculate_journal_stats(rows)
            return CommandResult(_format_journal_stats(stats))

        if action == "review":
            rows = self.journal.list(limit=10_000)
            stats = calculate_journal_stats(rows)
            prompt = build_journal_review_prompt(rows, stats)
            response = self._run_async(
                self.ai_provider.complete(AIRequest(prompt=prompt, model=self.config.settings.ai_model))
            )
            if not isinstance(response, AIResponse):
                raise CommandError("AI provider returned invalid data.")
            return CommandResult(
                MarkdownBlock("Journal Review", _format_ai_response(response), "Disclaimer: not financial advice.")
            )

        if action == "add":
            return self._journal_add(args[1:])

        if action == "edit":
            return self._journal_edit(args[1:])

        if action == "delete":
            return self._journal_delete(args[1:])

        if action == "show":
            if len(args) < 2:
                raise CommandError("Format: /journal show <id>")
            return self._journal_show(args[1])

        rows = self.journal.list(args[0])
        return CommandResult(self._journal_table(rows, f"Journal {args[0].upper()}"))

    def _journal_add(self, args: list[str]) -> CommandResult:
        if len(args) < 2:
            raise CommandError(
                'Format: /journal add <instrument> <bias> "entry reason" [--exit_reason ...] [--result win|loss|be] [--emotion ...] [--lesson ...] [--tags t1,t2]'
            )
        instrument = args[0]
        bias = args[1]
        entry_reason = ""
        exit_reason = ""
        result = ""
        emotion = ""
        lesson = ""
        tags = ""
        i = 2
        while i < len(args):
            if args[i] == "--exit_reason" and i + 1 < len(args):
                exit_reason = args[i + 1]
                i += 2
            elif args[i] == "--result" and i + 1 < len(args):
                result = args[i + 1]
                i += 2
            elif args[i] == "--emotion" and i + 1 < len(args):
                emotion = args[i + 1]
                i += 2
            elif args[i] == "--lesson" and i + 1 < len(args):
                lesson = args[i + 1]
                i += 2
            elif args[i] == "--tags" and i + 1 < len(args):
                tags = args[i + 1]
                i += 2
            else:
                entry_reason = args[i]
                i += 1
        self.journal.add(
            instrument,
            bias=bias,
            entry_reason=entry_reason,
            exit_reason=exit_reason,
            result=result,
            emotion=emotion,
            lesson=lesson,
            tags=tags,
        )
        return CommandResult(Panel(f"Journal entry for {instrument.upper()} added.", title="Journal"))

    def _journal_edit(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError(
                "Format: /journal edit <id> [--bias ...] [--entry_reason ...] [--exit_reason ...] [--result win|loss|be] [--emotion ...] [--lesson ...] [--tags t1,t2]"
            )
        try:
            entry_id = int(args[0])
        except ValueError:
            raise CommandError("ID must be a number.") from None
        fields: dict[str, str] = {}
        i = 1
        while i < len(args):
            key = args[i].lstrip("-")
            if key in {"bias", "entry_reason", "exit_reason", "result", "emotion", "lesson", "tags"} and i + 1 < len(
                args
            ):
                fields[key] = args[i + 1]
                i += 2
            else:
                i += 1
        if not fields:
            raise CommandError("No fields to update. Use --bias, --entry_reason, etc.")
        entry = self.journal.get(entry_id)
        if not entry:
            raise CommandError(f"Journal entry #{entry_id} not found.")
        self.journal.edit(entry_id, **fields)
        return CommandResult(Panel(f"Journal #{entry_id} updated.", title="Journal"))

    def _journal_delete(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /journal delete <id>")
        try:
            entry_id = int(args[0])
        except ValueError:
            raise CommandError("ID must be a number.") from None
        entry = self.journal.get(entry_id)
        if not entry:
            raise CommandError(f"Journal entry #{entry_id} not found.")
        self.journal.delete(entry_id)
        return CommandResult(Panel(f"Journal #{entry_id} ({entry['instrument']}) deleted.", title="Journal"))

    def _journal_show(self, id_str: str) -> CommandResult:
        try:
            entry_id = int(id_str)
        except ValueError:
            raise CommandError("ID must be a number.") from None
        entry = self.journal.get(entry_id)
        if not entry:
            raise CommandError(f"Journal entry #{entry_id} not found.")
        table = Table(title=f"Journal #{entry_id}", expand=True)
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value")
        for key in (
            "instrument",
            "bias",
            "entry_reason",
            "exit_reason",
            "result",
            "emotion",
            "lesson",
            "tags",
            "created_at",
        ):
            table.add_row(key.replace("_", " ").title(), str(entry.get(key) or "-"))
        return CommandResult(table)

    def _journal_table(self, rows: list[dict[str, object]], title: str) -> Table:
        table = Table(title=title, expand=True)
        table.add_column("ID", justify="right")
        table.add_column("Instrument", style="cyan")
        table.add_column("Bias")
        table.add_column("Entry Reason")
        table.add_column("Created")
        for row in rows:
            table.add_row(
                str(row["id"]),
                str(row["instrument"]),
                str(row["bias"]),
                str(row["entry_reason"]),
                str(row["created_at"]),
            )
        if not rows:
            table.add_row("-", "-", "-", 'No journal entries yet. Use /journal add BTC-USD bullish "Entry reason"', "-")
        return table

    def _portfolio_market_values(self, row: dict[str, object]) -> tuple[float | None, float | None, float | None]:
        try:
            symbol = str(row["symbol"])
            quantity = float(row["quantity"])
            average_price = float(row["average_price"])
            quote = self._get_quote(symbol)
            current_price = quote.price
            if current_price is None:
                return None, None, None
            pnl = (current_price - average_price) * quantity
            invested = average_price * quantity
            pnl_percent = (pnl / invested * 100) if invested else None
            return current_price, pnl, pnl_percent
        except FinCLIError:
            return None, None, None
        except (TypeError, ValueError, KeyError):
            return None, None, None

    def _portfolio_performance_table(self) -> Table:
        risk = self._portfolio_risk_report()

        table = Table(title="Portfolio Performance", expand=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Cost Basis", _fmt(risk.total_cost_basis))
        table.add_row("Market Value", _fmt(risk.total_market_value))
        table.add_row("Unrealized PnL", _fmt(risk.unrealized_pnl))
        table.add_row("Realized PnL", _fmt(risk.realized_pnl))
        table.add_row("Total PnL", _fmt(risk.total_pnl))
        table.add_row("Health Score", f"{risk.health.score}/100 ({risk.health.label})")
        return table

    def _portfolio_risk_report(self) -> PortfolioRiskReport:
        positions = self.portfolio.list()
        values: dict[str, tuple[float | None, float | None, float | None]] = {}
        for row in positions:
            values[str(row["symbol"]).upper()] = self._portfolio_market_values(row)
        return build_portfolio_risk(
            positions, values, self.transactions.realized_pnl_total(), profile=self.user_profiles.get()
        )

    def _portfolio_correlation(self) -> CommandResult:
        from fincli.app.modules.portfolio_risk import calculate_correlation_matrix

        positions = self.portfolio.list()
        if len(positions) < 2:
            return CommandResult(
                Panel("Need at least 2 positions for correlation matrix.", title="Portfolio Correlation")
            )

        symbols = [str(row["symbol"]).upper() for row in positions]
        price_history: dict[str, list[float]] = {}
        for symbol in symbols:
            try:
                candles = self._run_async(self.market_service.history(symbol, period="3mo", interval="1d"))
                price_history[symbol] = [c.close for c in candles] if candles else []
            except Exception:
                price_history[symbol] = []

        matrix = calculate_correlation_matrix(symbols, price_history)
        return CommandResult(_format_correlation_matrix(symbols, matrix))

    def _portfolio_tax(self) -> CommandResult:
        transactions = self.transactions.list()
        if not transactions:
            return CommandResult(Panel("No transactions yet. Use /tx add to record trades.", title="Portfolio Tax"))

        # Group by symbol
        by_symbol: dict[str, list[dict[str, object]]] = {}
        for tx in transactions:
            sym = str(tx["symbol"]).upper()
            if sym not in by_symbol:
                by_symbol[sym] = []
            by_symbol[sym].append(tx)

        return CommandResult(_format_portfolio_tax(by_symbol))

    def _portfolio_chart(self) -> CommandResult:
        from fincli.app.modules.portfolio_analytics import PortfolioAnalytics

        analytics = PortfolioAnalytics(self.db)
        snapshots = analytics.get_snapshots(limit=90)
        if not snapshots:
            return CommandResult(
                Panel(
                    "No portfolio snapshots yet. Use /portfolio snapshot to save current state.",
                    title="Portfolio Chart",
                )
            )
        ratios = analytics.calculate_risk_ratios()
        return CommandResult(_format_portfolio_chart(snapshots, ratios))

    def _portfolio_snapshot(self) -> CommandResult:
        from fincli.app.modules.portfolio_analytics import PortfolioAnalytics

        analytics = PortfolioAnalytics(self.db)
        positions = self.portfolio.list()
        values: dict[str, tuple[float | None, float | None, float | None]] = {}
        total_value = 0.0
        cost_basis = 0.0
        for row in positions:
            sym = str(row["symbol"]).upper()
            values[sym] = self._portfolio_market_values(row)
            qty = float(row["quantity"])
            avg = float(row["average_price"])
            cost_basis += qty * avg
            current, pnl, _ = values[sym]
            total_value += qty * float(current) if current is not None else qty * avg
        realized = self.transactions.realized_pnl_total()
        unrealized = total_value - cost_basis
        analytics.save_snapshot(
            total_value, cost_basis, unrealized, realized, {sym: {"value": v[0]} for sym, v in values.items()}
        )
        return CommandResult(
            Panel(
                f"Portfolio snapshot saved.\nTotal value: ${total_value:,.2f}\nCost basis: ${cost_basis:,.2f}\nPnL: ${unrealized + realized:,.2f}",
                title="Portfolio Snapshot",
                border_style="green",
            )
        )

    def _portfolio_history(self) -> CommandResult:
        rows = self.db.query(
            "SELECT id, total_value, cost_basis, unrealized_pnl, realized_pnl, created_at FROM portfolio_snapshots ORDER BY id DESC LIMIT 20"
        )
        if not rows:
            return CommandResult(
                Panel("No portfolio snapshots yet. Use /portfolio snapshot to save.", title="Portfolio History")
            )
        table = Table(title="Portfolio History (Last 20 Snapshots)", expand=True)
        table.add_column("#", style="dim", justify="right")
        table.add_column("Date", style="cyan")
        table.add_column("Total Value", justify="right")
        table.add_column("Cost Basis", justify="right")
        table.add_column("Unrealized", justify="right")
        table.add_column("Realized", justify="right")
        table.add_column("Total PnL", justify="right")
        for row in rows:
            uv = float(row["unrealized_pnl"])
            rv = float(row["realized_pnl"])
            table.add_row(
                str(row["id"]),
                str(row["created_at"])[:19],
                _fmt(float(row["total_value"])),
                _fmt(float(row["cost_basis"])),
                _fmt(uv),
                _fmt(rv),
                _fmt(uv + rv),
            )
        table.caption = "Use /portfolio snapshot to save current state. Use /portfolio chart for visual performance."
        return CommandResult(table)

    def _portfolio_whatif(self, args: list[str]) -> CommandResult:
        if len(args) < 4:
            raise CommandError("Format: /portfolio whatif <add|sell> <symbol> <qty> <price>")
        from fincli.app.modules.portfolio_analytics import PortfolioAnalytics

        action = args[0].lower()
        symbol = args[1].upper()
        quantity = float(args[2])
        price = float(args[3])
        analytics = PortfolioAnalytics(self.db)
        positions = self.portfolio.list()
        values: dict[str, tuple[float | None, float | None, float | None]] = {}
        for row in positions:
            values[str(row["symbol"]).upper()] = self._portfolio_market_values(row)
        result = analytics.what_if(action, symbol, quantity, price, positions, values)
        return CommandResult(_format_whatif(result))

    def _portfolio_benchmark(self, args: list[str]) -> CommandResult:
        benchmark_symbol = args[0].upper() if args else "SPY"
        from fincli.app.modules.portfolio_analytics import PortfolioAnalytics

        analytics = PortfolioAnalytics(self.db)
        snapshots = analytics.get_snapshots(limit=90)
        if len(snapshots) < 2:
            return CommandResult(
                Panel("Need at least 2 portfolio snapshots. Use /portfolio snapshot to save daily.", title="Benchmark")
            )

        # Get benchmark price history
        bench_candles = self._run_async(self.market_service.history(benchmark_symbol, period="3mo", interval="1d"))
        if not bench_candles:
            return CommandResult(Panel(f"No benchmark data for {benchmark_symbol}.", title="Benchmark"))

        portfolio_values = [s.total_value for s in reversed(snapshots)]
        benchmark_values = [c.close for c in bench_candles]
        comparison = analytics.compare_benchmark(benchmark_values, portfolio_values, benchmark_symbol)
        return CommandResult(_format_benchmark(comparison))

    def _portfolio_rebalance(self) -> CommandResult:
        """Suggest rebalancing trades based on equal-weight allocation."""
        rows = self.portfolio.list()
        if not rows:
            return CommandResult(
                Panel("Portfolio is empty. Add positions first with /portfolio add.", title="Rebalance")
            )

        # Calculate current values
        positions = []
        total_value = 0.0
        for row in rows:
            symbol = str(row["symbol"])
            quantity = float(row["quantity"])
            avg_price = float(row["average_price"])
            try:
                quote = self._get_quote(symbol)
                current_price = quote.price
            except (httpx.HTTPError, ProviderError) as exc:
                logger.debug("Price fetch failed for %s: %s", symbol, exc)
                current_price = avg_price
            market_value = quantity * current_price
            total_value += market_value
            positions.append(
                {
                    "symbol": symbol,
                    "quantity": quantity,
                    "current_price": current_price,
                    "market_value": market_value,
                }
            )

        if total_value <= 0:
            return CommandResult(Panel("Total portfolio value = 0. Cannot rebalance.", title="Rebalance"))

        # Equal-weight target
        n = len(positions)
        target_value = total_value / n
        target_pct = 100.0 / n

        # Calculate rebalance trades
        trades = []
        for pos in positions:
            diff_value = target_value - pos["market_value"]
            if abs(diff_value) > 1.0:  # Only suggest if difference > $1
                side = "buy" if diff_value > 0 else "sell"
                qty = abs(diff_value) / pos["current_price"]
                trades.append(
                    {
                        "symbol": pos["symbol"],
                        "side": side,
                        "quantity": qty,
                        "value": abs(diff_value),
                        "current_pct": (pos["market_value"] / total_value) * 100,
                        "target_pct": target_pct,
                    }
                )

        return CommandResult(_format_rebalance(positions, trades, total_value, target_pct))
