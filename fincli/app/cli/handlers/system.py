"""Command parsing and routing."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from pathlib import Path

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fincli import __version__
from fincli.app.analysis.assistant_context import (
    build_web_research_answer_prompt,
)
from fincli.app.cli.handlers.common import (
    _doctor_live_symbol,
    _format_agent,
    _format_agents,
    _format_ai_response,
    _format_audit_events,
    _format_connectors,
    _format_dashboard,
    _format_plugin_validation,
    _format_plugins,
    _format_secret_ages,
    _format_secrets_status,
    _format_security_scan,
    _format_security_status,
    _format_session_events,
    _format_session_picker,
    _format_session_security,
    _format_theme_current,
    _format_theme_list,
    _format_tutorial_menu,
    _format_user_profile,
    _format_web_results,
    _router_roots,
    _tutorial_lesson,
    _tutorial_next,
)
from fincli.app.cli.result import CommandResult
from fincli.app.diagnostics.capabilities import capability_rows, capability_summary
from fincli.app.diagnostics.runtime import check_runtime_environment
from fincli.app.modules.journal_analytics import calculate_journal_stats
from fincli.app.modules.session_history import relative_time
from fincli.app.plugins.loader import PluginLoader
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.services.web_research import (
    build_web_research_context,
)
from fincli.app.storage.audit_log import EVENT_SECURITY_VIOLATION
from fincli.app.storage.secrets import clear_secrets, read_secrets
from fincli.app.utils.errors import CommandError, FinCLIError
from fincli.app.utils.i18n import get_language, set_language, t
from fincli.app.utils.security import SecurityValidator

logger = logging.getLogger(__name__)

# Constants
PROVIDER_TIMEOUT_BUFFER_SECONDS = 15.0


class SystemCommands:
    """System command handlers."""

    def _help_table(self) -> Table:
        table = Table(title=t("help.title", version=__version__), expand=True)
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Group", style="magenta")
        table.add_column("Description", style="white")
        table.add_column("Example", style="green")
        for command in self.registry.all():
            table.add_row(command.name, command.group, command.description, command.example)
        return table

    def _history(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "picker"
        # /history resume [<id|#>] — resume session
        if action == "resume":
            return self._history_resume(args[1:])
        # /history show <id> — show session detail
        if action == "show":
            if len(args) < 2:
                raise CommandError("Format: /history show <session_id>")
            session_id = args[1]
            session = self.history.get_session(session_id)
            if not session:
                raise CommandError(f"Session not found: {session_id}")
            events = self.history.get_events(session_id)
            return CommandResult(_format_session_events(session, events, current=session_id == self.session_id))
        # /history current — show current session events
        if action == "current":
            events = self.history.get_events(self.session_id)
            session = self.history.get_session(self.session_id)
            return CommandResult(_format_session_events(session, events, current=True))
        # /history save <title>
        if action == "save":
            title = " ".join(args[1:]).strip()
            if not title:
                raise CommandError('Format: /history save "judul session"')
            self.history.save_session(self.session_id, title)
            return CommandResult(Panel(f"Current session saved as: {title}", title="History", border_style="green"))
        # /history delete <id>
        if action == "delete":
            if len(args) < 2:
                raise CommandError("Format: /history delete <session_id>")
            if args[1] == self.session_id:
                self.history.clear_events(self.session_id)
                self.history.save_session(self.session_id, "FinCLI session")
                return CommandResult(Panel("Current session cleared.", title="History", border_style="yellow"))
            self.history.delete_session(args[1])
            return CommandResult(Panel(f"Session deleted: {args[1]}", title="History", border_style="green"))
        # /history clear [current|all]
        if action == "clear":
            target = args[1].lower() if len(args) >= 2 else "current"
            if target == "all":
                self.history.clear_all()
                self.session_id = self.history.start_session()
                return CommandResult(Panel("All session history cleared. New session created.", title="History"))
            self.history.clear_events(self.session_id)
            return CommandResult(Panel("Current session history cleared.", title="History"))
        # /history — session picker (default, like Claude Code /resume)
        sessions = self.history.list_sessions()
        return CommandResult(_format_session_picker(sessions, self.session_id, self.history.get_session_summary))

    def _history_resume(self, args: list[str]) -> CommandResult:
        """Resume a previous session — load context from it."""
        if not args:
            # Resume most recent non-current session
            last = self.history.get_last_session(self.session_id)
            if not last:
                return CommandResult(
                    Panel("No other sessions yet. Run some commands first.", title="History", border_style="dim"),
                )
            session_id = str(last["id"])
        else:
            target = args[0]
            # Allow resume by number (from picker list)
            sessions = self.history.list_sessions()
            if target.isdigit():
                idx = int(target) - 1
                if 0 <= idx < len(sessions) and str(sessions[idx]["id"]) != self.session_id:
                    session_id = str(sessions[idx]["id"])
                else:
                    raise CommandError(f"Invalid session number: {target}")
            else:
                session_id = target
        if session_id == self.session_id:
            raise CommandError("Already in this session. Use /history current to view commands.")
        data = self.history.resume_session(session_id)
        if not data:
            raise CommandError(f"Session not found: {session_id}")
        session = data["session"]
        events = data["events"]
        summary = self.history.get_session_summary(session_id)
        ts = relative_time(str(session.get("updated_at", session.get("created_at", ""))))
        # Build resume output
        header = Panel(
            f"[bold]Resumed session [cyan]{session_id}[/cyan][/]\n"
            f"[dim]{ts}[/] · [dim]{len(events)} commands[/]\n"
            f"[dim]{summary}[/]",
            title="History — Resume",
            border_style="cyan",
        )
        # Show last few commands as context
        recent = events[-8:] if len(events) > 8 else events
        table = Table(title="Recent Commands", expand=True, show_lines=False)
        table.add_column("#", justify="right", width=4, style="dim")
        table.add_column("Command", style="white")
        table.add_column("Status", style="cyan", width=8)
        table.add_column("When", style="dim")
        for ev in recent:
            table.add_row(
                str(ev["id"]),
                str(ev["command"])[:60],
                str(ev["status"]),
                relative_time(str(ev["created_at"])),
            )
        caption = Text.from_markup(
            f"[dim]Session {session_id} loaded. Type /history show {session_id} for full detail.[/]"
        )
        return CommandResult(Group(header, table, caption))

    def _session(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /session save|restore|status")
        action = args[0].lower()
        if action == "save":
            saved = self.session_state.save(force=True)
            if saved:
                return CommandResult(Panel("Session state saved.", title="Session", border_style="green"))
            return CommandResult(Panel("No changes to save.", title="Session", border_style="yellow"))
        if action == "restore":
            unclean = self.session_state.get_last_unclean_state()
            if not unclean:
                return CommandResult(
                    Panel("No unclean session found to restore.", title="Session", border_style="yellow")
                )
            self.session_state.restore_state(unclean)
            summary = self.session_state.get_recovery_summary(unclean)
            return CommandResult(
                Panel(
                    f"Session restored:\n{summary}",
                    title="Session Restored",
                    border_style="green",
                )
            )
        if action == "status":
            state = self.session_state.current_state
            if not state:
                return CommandResult(Panel("Session state not initialized.", title="Session", border_style="yellow"))
            table = Table(title="Session State Status", show_header=False, border_style="cyan")
            table.add_column("Field", style="bold")
            table.add_column("Value")
            table.add_row("Session ID", state.session_id[:12] + "...")
            table.add_row("Command Buffer", state.command_buffer or "(empty)")
            table.add_row("Output Entries", str(len(state.output_entries)))
            table.add_row("Status Bar", state.status_bar or "(empty)")
            table.add_row("Dirty", "Yes" if state.is_dirty else "No")
            return CommandResult(table)
        raise CommandError("Format: /session save|restore|status")

    def _lang(self, args: list[str]) -> CommandResult:
        """Change display language."""
        if not args:
            current = get_language()
            table = Table(title="Language Settings", show_header=False, border_style="cyan")
            table.add_column("Field", style="bold")
            table.add_column("Value")
            table.add_row("Current", current)
            table.add_row("Supported", "en (English), id (Indonesia)")
            table.add_row("Usage", "/lang en | /lang id")
            return CommandResult(table)

        lang = args[0].lower()
        if lang not in ("en", "id"):
            raise CommandError("Language not supported. Use 'en' (English) or 'id' (Indonesia).")

        set_language(lang)
        self.config.settings.language = lang
        self.config.save()

        if lang == "en":
            msg = "Language changed to English."
        else:
            msg = "Language changed to Indonesian."

        return CommandResult(Panel(msg, title="Language", border_style="green"))

    def _dashboard(self) -> Table:
        return _format_dashboard(
            provider_chain=[provider.name for provider in self.market_service.providers],
            watchlist_rows=self.watchlist.list(),
            portfolio_rows=self.portfolio.list(),
            journal_stats=calculate_journal_stats(self.journal.list(limit=10_000)),
            realized_pnl=self.transactions.realized_pnl_total(),
            quote_getter=self._safe_quote,
            portfolio_value_getter=self._portfolio_market_values,
            alerts_rows=self.alerts.list(active_only=True),
        )

    def _theme(self, args: list[str]) -> CommandResult:
        from fincli.app.tui.themes import (
            THEMES,
            ThemePreset,
            get_theme,
            list_themes,
            load_custom_theme,
            register_custom_theme,
            save_custom_theme,
        )

        if not args:
            current = getattr(self.config.settings, "theme", "midnight")
            t = get_theme(current)
            return CommandResult(_format_theme_current(t, list_themes()))
        action = args[0].lower()
        if action in {"list", "ls"}:
            return CommandResult(_format_theme_list(list_themes()))
        if action == "create":
            if len(args) < 2:
                raise CommandError("Format: /theme create <name> [--base midnight]")
            name = args[1]
            base_name = args[3] if len(args) >= 4 and args[2] == "--base" else "midnight"
            base = get_theme(base_name)
            custom = ThemePreset(
                name=name,
                description=f"custom theme (based on {base_name})",
                bg=base.bg,
                bg_alt=base.bg_alt,
                text=base.text,
                muted=base.muted,
                accent=base.accent,
                border=base.border,
                positive=base.positive,
                negative=base.negative,
                caution=base.caution,
                gradient_start=base.gradient_start,
                gradient_end=base.gradient_end,
                gradient_angle=base.gradient_angle,
            )
            from fincli.app.storage import config_paths

            path = config_paths.APP_DIR / "themes" / f"{name}.json"
            save_custom_theme(path, custom)
            register_custom_theme(custom)
            return CommandResult(
                Panel(
                    f"Theme '{name}' created at {path}. Edit JSON to customize colors.",
                    title="Theme Created",
                    border_style="green",
                )
            )
        if action == "import":
            if len(args) < 2:
                raise CommandError("Format: /theme import <path.json>")
            path = SecurityValidator.validate_path(args[1], allowed_dirs=[Path.home(), Path.cwd()])
            if not path.exists():
                raise CommandError(f"File not found: {path}")
            custom = load_custom_theme(path)
            register_custom_theme(custom)
            return CommandResult(
                Panel(f"Theme '{custom.name}' imported and registered.", title="Theme Imported", border_style="green")
            )
        if action == "export":
            if len(args) < 3:
                raise CommandError("Format: /theme export <theme_name> <path.json>")
            theme_name = args[1]
            t = get_theme(theme_name)
            path = SecurityValidator.validate_path(args[2], allowed_dirs=[Path.home(), Path.cwd()])
            save_custom_theme(path, t)
            return CommandResult(
                Panel(f"Theme '{theme_name}' exported to {path}.", title="Theme Exported", border_style="green")
            )
        if action in THEMES:
            # Store theme — actual CSS reload happens in TUI layer
            self.config.settings.theme = action
            self.config.save()
            t = get_theme(action)
            return CommandResult(
                Panel(f"Theme changed to: [bold]{t.name}[/] — {t.description}", title="Theme", border_style=t.accent),
                metadata={"theme_changed": action},
            )
        raise CommandError(f"Unknown theme: {action}. Use /theme list.")

    def _config_panel(self) -> Panel:
        safe = self.config.settings.safe_dict()
        lines = [
            f"AI provider       : {safe['ai_provider']}",
            f"AI model          : {safe['ai_model']}",
            f"Market provider   : {safe['market_provider']}",
            f"News provider     : {safe['news_provider']}",
            f"News priority     : {', '.join(safe.get('news_provider_priority', []))}",
            f"Timezone          : {safe['timezone']}",
            f"Default currency  : {safe['default_currency']}",
            f"Cache TTL         : {safe['cache_ttl_seconds']}s",
            f"Provider timeout  : {safe['provider_timeout_seconds']}s",
            f"Circuit breaker   : {safe['provider_circuit_breaker_failure_threshold']} failures / {safe['provider_circuit_breaker_cooldown_seconds']}s cooldown",
            f"Theme             : {safe['theme']}",
            "",
            "API key status:",
        ]
        lines.extend(f"- {key}: {value}" for key, value in safe["api_keys"].items())
        return Panel("\n".join(lines), title="Active Config", border_style="cyan")

    def _profile(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(_format_user_profile(self.user_profiles.get()))
        action = args[0].lower()
        if action == "set":
            if len(args) < 6:
                raise CommandError('Format: /profile set "Nama" <equity> <currency> <leverage> <years>')
            profile = self.user_profiles.save(args[1], float(args[2]), args[3], args[4], float(args[5]))
            return CommandResult(_format_user_profile(profile))
        if action in {"clear", "delete", "reset"}:
            self.user_profiles.clear()
            return CommandResult(Panel("Local profile deleted.", title="Profile", border_style="yellow"))
        raise CommandError(
            'Format: /profile, /profile set "Nama" <equity> <currency> <leverage> <years>, /profile clear'
        )

    def _doctor(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "report":
            return self._doctor_report()
        full = bool(args and args[0].lower() in {"full", "deep"})
        live = "--live" in {arg.lower() for arg in args}
        live_symbol = _doctor_live_symbol(args)
        table = Table(title="FinCLI Doctor Full" if full else "FinCLI Doctor", expand=True)
        table.add_column("Check", style="cyan", no_wrap=True)
        table.add_column("Status")
        table.add_column("Detail", overflow="fold")
        table.add_row("Version", "ok", f"FinCLI v{__version__} command surface loaded.")
        for check in check_runtime_environment():
            style = "green" if check.status == "ok" else "yellow" if check.status in {"warning", "info"} else "red"
            table.add_row(check.name, f"[{style}]{check.status}[/]", check.detail)
        table.add_row("Database", "ok", str(self.db.db_file))
        table.add_row("Market Provider", "ok", ", ".join(provider.name for provider in self.market_service.providers))
        table.add_row("Provider Timeout", "ok", f"{self.config.settings.provider_timeout_seconds}s per provider call")
        table.add_row(
            "Circuit Breaker",
            "ok",
            (
                f"{self.config.settings.provider_circuit_breaker_failure_threshold} failures -> "
                f"{self.config.settings.provider_circuit_breaker_cooldown_seconds}s cooldown"
            ),
        )
        profile = self.user_profiles.get()
        table.add_row(
            "Profile", "ok" if profile else "missing", profile.gameplay if profile else "Run /profile set ..."
        )
        table.add_row(
            "AI Provider", "configured", f"{self.config.settings.ai_provider} / {self.config.settings.ai_model}"
        )
        from fincli.app.web.manager import WebServerManager

        web_status = WebServerManager(self.config).status()
        table.add_row(
            "Local Web",
            "ok" if web_status["running"] else "info",
            f"{'running' if web_status['running'] else 'stopped'} at {web_status['url']}; auth={'required' if web_status['auth'] else 'disabled'}",
        )
        if full:
            for name, status, detail in self._doctor_full_checks():
                style = "green" if status == "ok" else "yellow" if status in {"warning", "info"} else "red"
                table.add_row(name, f"[{style}]{status}[/]", detail)
            if live:
                for name, status, detail in self._doctor_live_checks(live_symbol):
                    style = "green" if status == "ok" else "yellow" if status in {"warning", "info"} else "red"
                    table.add_row(name, f"[{style}]{status}[/]", detail)
        table.caption = (
            "Doctor full checks local wiring, command coverage, database/cache, and provider configuration. "
            "Use /doctor full --live [SYMBOL] for optional live quote verification. "
            "Provider entitlement still depends on API key/account plan."
        )
        return CommandResult(table)

    def _doctor_full_checks(self) -> list[tuple[str, str, str]]:
        checks: list[tuple[str, str, str]] = []
        try:
            tables = self.db.query("SELECT name FROM sqlite_master WHERE type = 'table'")
            checks.append(("Database Schema", "ok", f"{len(tables)} table(s) available"))
        except FinCLIError as exc:
            checks.append(("Database Schema", "error", str(exc)))

        try:
            stats = self.market_cache.stats()
            checks.append(("Market Cache", "ok", ", ".join(f"{key}={value}" for key, value in stats.items())))
        except FinCLIError as exc:
            checks.append(("Market Cache", "error", str(exc)))

        key_rows = self.market_manager.key_status()
        missing_keys = [row["provider"] for row in key_rows if row["status"] == "not set"]
        configured_keys = [row["provider"] for row in key_rows if row["status"] not in {"not set", "not required"}]
        checks.append(
            (
                "Market API Keys",
                "warning" if missing_keys else "ok",
                f"configured={len(configured_keys)}; missing={', '.join(missing_keys) if missing_keys else 'none'}",
            )
        )

        for provider in self.market_service.providers:
            provider_name = getattr(provider, "name", "unknown")
            try:
                status = self._run_async(provider.status())
                checks.append(
                    (
                        f"Provider:{provider_name}",
                        "ok" if status.status in {"ok", "configured", "fallback"} else "warning",
                        status.message,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append((f"Provider:{provider_name}", "error", str(exc)))

        registry_roots = {command.name.split()[0] for command in self.registry.all()}
        router_roots = _router_roots()
        hidden = sorted(router_roots - registry_roots)
        stale = sorted(registry_roots - router_roots)
        if hidden or stale:
            checks.append(
                (
                    "Command Coverage",
                    "warning",
                    f"hidden={', '.join(hidden) if hidden else 'none'}; stale={', '.join(stale) if stale else 'none'}",
                )
            )
        else:
            checks.append(
                ("Command Coverage", "ok", f"{len(registry_roots)} registry root command(s) covered by router")
            )

        metric_snapshot = self.market_service.provider_metrics_snapshot()
        checks.append(("Provider Metrics", "ok", f"session_providers={len(metric_snapshot)}; persistent_store=enabled"))
        checks.append(("Capability Matrix", "ok", capability_summary()))
        for capability in capability_rows():
            checks.append(
                (
                    f"Capability:{capability.command}",
                    "ok",
                    f"needs={', '.join(capability.needs)}; {capability.note}",
                )
            )
        return checks

    def _doctor_live_checks(self, symbol: str) -> list[tuple[str, str, str]]:
        try:
            quote = self._run_async(
                asyncio.wait_for(self.market_service.quote(symbol), self.config.settings.provider_timeout_seconds)
            )
        except Exception as exc:  # noqa: BLE001
            return [("Live Quote Test", "error", f"{symbol}: {type(exc).__name__}: {exc}")]
        return [
            (
                "Live Quote Test",
                "ok" if quote.price is not None else "warning",
                f"{quote.symbol} {quote.price if quote.price is not None else 'N/A'} {quote.currency}; provider={quote.provider}; status={quote.status}",
            )
        ]

    def _doctor_report(self) -> CommandResult:
        import platform
        import sys

        lines = [
            "=== FinCLI Diagnostic Report ===",
            "",
            f"Version      : {__version__}",
            f"Python       : {sys.version.split()[0]}",
            f"Platform     : {platform.platform()}",
            f"Database     : {self.db.db_file}",
            "",
            "--- Provider Chain ---",
        ]
        for provider in self.market_service.providers:
            name = getattr(provider, "name", "unknown")
            cap = getattr(provider, "capabilities", lambda: None)()
            if cap:
                lines.append(f"  {name}: realtime={cap.realtime}, ops={','.join(cap.operations)}")
            else:
                lines.append(f"  {name}: capabilities=unknown")
        lines.append("")
        lines.append("--- Provider Metrics (Session) ---")
        for name, metric in self.market_service.provider_metrics_snapshot().items():
            lines.append(
                f"  {name}: calls={metric.calls}, success_rate={metric.success_rate:.1f}%, errors={metric.errors}"
            )
        lines.append("")
        lines.append("--- API Key Status ---")
        for row in self.market_manager.key_status():
            lines.append(f"  {row['provider']}: {row['status']}")
        lines.append("")
        lines.append("--- Database Tables ---")
        try:
            tables = self.db.query("SELECT name FROM sqlite_master WHERE type='table'")
            lines.append(f"  {len(tables)} table(s): {', '.join(str(t['name']) for t in tables)}")
        except Exception as exc:
            lines.append(f"  Error: {exc}")
        lines.append("")
        lines.append("--- Active Config (no secrets) ---")
        safe = self.config.settings.safe_dict()
        for key, value in safe.items():
            if key != "api_keys":
                lines.append(f"  {key}: {value}")
        lines.append("")
        lines.append("=== End Report ===")
        lines.append("")
        lines.append("This report contains no API keys or secrets.")
        lines.append("Share this output when filing a bug report.")
        report_text = "\n".join(lines)
        return CommandResult(Panel(report_text, title="Doctor Report", border_style="cyan"))

    def _setup(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "check":
            return CommandResult(self._setup_check())
        if args and args[0].lower() == "keys":
            return self._setup_keys()
        if args and args[0].lower() == "profile":
            return self._setup_profile()
        if args and args[0].lower() == "theme":
            return self._setup_theme()
        return CommandResult(self._setup_wizard())

    def _setup_wizard(self) -> Table:
        table = Table(title="FinCLI Setup Wizard", expand=True)
        table.add_column("Step", style="cyan", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Action", overflow="fold")

        # Check profile
        try:
            profile_rows = self.db.query("SELECT name FROM user_profile WHERE id = 1")
            if profile_rows:
                table.add_row("1. Profile", "[green]OK[/]", f"Welcome back, {profile_rows[0]['name']}")
            else:
                table.add_row("1. Profile", "[yellow]MISSING[/]", "/setup profile — set name, equity, currency")
        except sqlite3.OperationalError as exc:
            logger.debug("Profile check failed: %s", exc)
            table.add_row("1. Profile", "[yellow]MISSING[/]", "/setup profile")

        # Check AI key
        secrets = read_secrets()
        ai_keys = [k for k in secrets if "AI" in k.upper() or "GROQ" in k.upper() or "OPENAI" in k.upper()]
        if ai_keys:
            table.add_row("2. AI Key", "[green]OK[/]", f"{len(ai_keys)} key(s) configured")
        else:
            table.add_row("2. AI Key", "[yellow]MISSING[/]", "/ai_model key groq <api_key>")

        # Check market key
        market_keys = [
            k for k in secrets if any(p in k.upper() for p in ["FINNHUB", "ALPHA", "TWELVEDATA", "MARKETAUX"])
        ]
        if market_keys:
            table.add_row("3. Market Key", "[green]OK[/]", f"{len(market_keys)} key(s) configured")
        else:
            table.add_row("3. Market Key", "[yellow]MISSING[/]", "/news_model key finnhub <api_key>")

        # Check theme
        current_theme = getattr(self.config.settings, "theme", "midnight")
        table.add_row("4. Theme", "[green]OK[/]", f"Current: {current_theme}. /theme list to change.")

        # Quick start
        table.add_row("5. Test", "[dim]-[/]", "/research AAPL --quick")
        table.add_row("6. Test", "[dim]-[/]", "/analyze XAUUSD 1d")

        table.caption = "Run: /setup check | /setup keys | /setup profile | /setup theme"
        return table

    def _setup_check(self) -> Table:
        """Detailed configuration check."""
        table = Table(title="Configuration Check", expand=True)
        table.add_column("Check", style="cyan", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Detail", overflow="fold")

        secrets = read_secrets()
        # Profile
        try:
            profile_rows = self.db.query("SELECT name, equity, currency FROM user_profile WHERE id = 1")
            if profile_rows:
                p = profile_rows[0]
                table.add_row("Profile", "ok", f"{p['name']} | {p['equity']} {p['currency']}")
            else:
                table.add_row("Profile", "missing", "Run /setup profile")
        except sqlite3.OperationalError as exc:
            logger.debug("Profile read failed: %s", exc)
            table.add_row("Profile", "error", "Cannot read profile")

        # Keys
        for key_name in ["GROQ_API_KEY", "OPENAI_API_KEY", "FINNHUB_API_KEY", "ALPHAVANTAGE_API_KEY"]:
            if secrets.get(key_name):
                table.add_row(key_name, "ok", "***configured***")
            else:
                table.add_row(key_name, "missing", "Run /ai_model key or /news_model key")

        # Theme
        theme = getattr(self.config.settings, "theme", "midnight")
        table.add_row("Theme", "ok", theme)

        # Database
        table.add_row("Database", "ok", str(self.db.db_file))

        return table

    def _setup_keys(self) -> CommandResult:
        """Guide through API key setup."""
        secrets = read_secrets()
        lines = [
            "[bold]API Key Setup[/]",
            "",
            "[cyan]AI Providers:[/]",
            "  /ai_model key groq <api_key>        — free tier, fast",
            "  /ai_model key openai <api_key>      — GPT-4o",
            "  /ai_model key anthropic <api_key>   — Claude",
            "",
            "[cyan]Market Data:[/]",
            "  /news_model key finnhub <api_key>   — free tier, news + calendar",
            "  /news_model key alphavantage <key>  — macro data",
            "  /news_model key twelvedata <key>    — technical data",
        ]
        if secrets:
            lines.append("")
            lines.append("[green]Configured:[/]")
            for k in sorted(secrets):
                lines.append(f"  {k}: ***")
        return CommandResult(Panel("\n".join(lines), title="API Keys", border_style="cyan"))

    def _setup_profile(self) -> CommandResult:
        """Guide through profile setup."""
        try:
            profile_rows = self.db.query(
                "SELECT name, equity, currency, leverage, years_in_investment, gameplay FROM user_profile WHERE id = 1"
            )
            if profile_rows:
                p = profile_rows[0]
                return CommandResult(
                    Panel(
                        f"Name: {p['name']}\nEquity: {p['equity']} {p['currency']}\nLeverage: {p['leverage']}\nYears: {p['years_in_investment']}\nGameplay: {p['gameplay']}",
                        title="Current Profile",
                        border_style="green",
                    )
                )
        except sqlite3.OperationalError as exc:
            logger.debug("Profile query failed: %s", exc)
        return CommandResult(
            Panel(
                'No profile set.\n\nRun:\n/profile set "Your Name" 10000 USD 1x 3 conservative',
                title="Profile Setup",
                border_style="yellow",
            )
        )

    def _setup_theme(self) -> CommandResult:
        """Guide through theme setup."""
        from fincli.app.tui.themes import list_themes

        themes = list_themes()
        current = getattr(self.config.settings, "theme", "midnight")
        lines = [f"Current: [bold]{current}[/]", "", "Available themes:"]
        for theme in themes:
            marker = " [green]<-- current[/]" if theme.name == current else ""
            lines.append(f"  /theme {theme.name} — {theme.description}{marker}")
        lines.append("\nRun: /theme <name> to change.")
        return CommandResult(Panel("\n".join(lines), title="Theme Setup", border_style="cyan"))

    def _tutorial(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(_format_tutorial_menu())
        action = args[0].lower()
        if action == "next":
            return CommandResult(_tutorial_next(self))
        if action == "reset":
            if not hasattr(self, "_tutorial_progress"):
                self._tutorial_progress = 0
            self._tutorial_progress = 0
            return CommandResult(
                Panel("Tutorial progress reset. Type /tutorial to start over.", title="Tutorial", border_style="yellow")
            )
        if action in {"1", "setup", "welcome"}:
            return CommandResult(_tutorial_lesson(1))
        if action in {"2", "market", "data"}:
            return CommandResult(_tutorial_lesson(2))
        if action in {"3", "technical", "analysis"}:
            return CommandResult(_tutorial_lesson(3))
        if action in {"4", "portfolio"}:
            return CommandResult(_tutorial_lesson(4))
        if action in {"5", "trading"}:
            return CommandResult(_tutorial_lesson(5))
        if action in {"6", "alerts", "monitoring"}:
            return CommandResult(_tutorial_lesson(6))
        if action in {"7", "export", "reports"}:
            return CommandResult(_tutorial_lesson(7))
        raise CommandError("Format: /tutorial, /tutorial <1-7>, /tutorial next, /tutorial reset")

    def _secrets(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "status"
        if action == "status":
            return CommandResult(_format_secrets_status(read_secrets()))
        if action == "clear":
            cleared = clear_secrets()
            return CommandResult(
                Panel(
                    f"{cleared} local secret(s) cleared from ~/.fincli/secrets.env. Current process keys from that store were removed.",
                    title="Secrets Cleared",
                    border_style="yellow",
                )
            )
        if action == "age":
            return CommandResult(_format_secret_ages())
        if action == "rotate":
            if len(args) < 2:
                raise CommandError("Format: /secrets rotate <PROVIDER_KEY>")
            return self._rotate_secret(args[1])
        raise CommandError("Format: /secrets status, /secrets clear, /secrets age, /secrets rotate <KEY>")

    def _rotate_secret(self, env_key: str) -> CommandResult:
        from fincli.app.storage.secrets import rotate_secret

        key = env_key.strip().upper()
        if not key or not all(c.isalnum() or c == "_" for c in key):
            raise CommandError(f"Invalid key name: {env_key}")
        # Check if key exists
        current = os.getenv(key)
        if not current:
            raise CommandError(f"Key {key} is not currently set. Use /ai_model key or /news_model key first.")
        # Prompt for new value
        new_value = input(f"Enter new value for {key}: ").strip()
        if not new_value:
            raise CommandError("New value cannot be empty.")
        if new_value == current:
            raise CommandError("New value is the same as the current value.")
        rotate_secret(key, new_value)
        masked = new_value[:4] + "..." + new_value[-4:] if len(new_value) > 8 else "****"
        return CommandResult(
            Panel(
                f"Key {key} rotated successfully.\nNew value: {masked}",
                title="Key Rotated",
                border_style="green",
            )
        )

    def _security(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(_format_security_status(self))
        action = args[0].lower()
        if action == "status":
            return CommandResult(_format_security_status(self))
        if action == "audit":
            limit = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 50
            events = self.audit_log.list_events(limit=limit)
            return CommandResult(_format_audit_events(events))
        if action == "scan":
            return CommandResult(_format_security_scan(read_secrets()))
        if action == "lockdown":
            # Emergency: clear all secrets
            cleared = clear_secrets()
            self.audit_log.record(EVENT_SECURITY_VIOLATION, f"Emergency lockdown: {cleared} secrets cleared")
            return CommandResult(
                Panel(
                    f"LOCKDOWN: {cleared} secrets cleared. All API keys removed. Use /ai_model key and /news_model key to reconfigure.",
                    title="Security Lockdown",
                    border_style="red",
                )
            )
        if action == "purge":
            # Purge: clear secrets, session history, cache
            secrets_cleared = clear_secrets()
            self.history.clear_events(self.session_id)
            self.cache.clear()
            cache_cleared = self.market_cache.clear()
            self.audit_log.record("security_purge", f"Purged: {secrets_cleared} secrets, session history, cache")
            return CommandResult(
                Panel(
                    (
                        f"Security state purged.\n"
                        f"- secrets cleared: {secrets_cleared}\n"
                        f"- current session history cleared\n"
                        f"- runtime cache cleared\n"
                        f"- persistent market cache rows cleared: {cache_cleared}\n\n"
                        "Portfolio, journal, alerts, and profile were kept."
                    ),
                    title="Security Purge",
                    border_style="yellow",
                )
            )
        if action == "session":
            return CommandResult(_format_session_security(self))
        raise CommandError(
            "Format: /security status, /security audit, /security scan, /security lockdown, "
            "/security purge, /security session"
        )

    def _agent(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "list"
        if action in {"list", "ls"}:
            category = args[1].lower() if len(args) >= 2 else ""
            agents = self.agent_registry.by_category(category) if category else list(self.agent_registry.all())
            return CommandResult(_format_agents(agents, category or "all"))
        if action == "show":
            if len(args) < 2:
                raise CommandError("Format: /agent show <slug>")
            agent = self.agent_registry.get(args[1])
            if agent is None:
                raise CommandError(f"Agent not found: {args[1]}")
            return CommandResult(_format_agent(agent))
        raise CommandError("Format: /agent list [category] or /agent show <slug>")

    def _connector(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "list"
        if action in {"list", "ls"}:
            category = args[1].lower() if len(args) >= 2 else ""
            connectors = (
                self.connector_catalog.by_category(category) if category else list(self.connector_catalog.all())
            )
            return CommandResult(_format_connectors(connectors, category or "all"))
        if action in {"search", "find"}:
            if len(args) < 2:
                raise CommandError("Format: /connector search <query>")
            query = " ".join(args[1:])
            return CommandResult(_format_connectors(self.connector_catalog.find(query), query))
        raise CommandError("Format: /connector list [category], /connector search <query>")

    def _plugin(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "list"
        if action in {"list", "ls", "status"}:
            plugins = PluginLoader().discover()
            return CommandResult(_format_plugins(plugins, status_only=action == "status"))
        if action == "validate":
            plugins = PluginLoader().discover()
            from fincli.app.plugins.loader import validate_manifest

            results = []
            for plugin in plugins:
                errors = validate_manifest(plugin)
                results.append((plugin, errors))
            return CommandResult(_format_plugin_validation(results))
        raise CommandError("Format: /plugin list, /plugin status, or /plugin validate")

    def _cache(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "stats":
            stats = self.market_cache.stats()
            lines = [
                f"Runtime cache TTL  : {self.config.settings.cache_ttl_seconds}s",
                f"Persistent entries: {stats['total']}",
                f"- quote          : {stats['quote']}",
                f"- history        : {stats['history']}",
                f"- news           : {stats['news']}",
                f"- fundamentals   : {stats['fundamentals']}",
            ]
            return CommandResult(Panel("\n".join(lines), title="Cache Stats", border_style="cyan"))
        if args and args[0].lower() == "clear":
            self.cache.clear()
            cleared = self.market_cache.clear()
            return CommandResult(
                Panel(f"Runtime cache and persistent cache cleared ({cleared} entries).", title="Cache")
            )
        raise CommandError("Format: /cache clear, /cache stats")

    def _web(self, args: list[str]) -> CommandResult:
        web_actions = {"start", "stop", "restart", "status", "open", "token", "logs", "config"}
        if not args or args[0].lower() in web_actions:
            return self._local_web(args)
        if args[0].lower() in {"sources", "source", "raw"}:
            source_query = " ".join(args[1:]).strip()
            if not source_query:
                raise CommandError("Format: /web sources <query>")
            results = self._run_async(self.web_research.research(source_query, limit=5))
            return CommandResult(_format_web_results(source_query, results))

        query = " ".join(args)
        results = self._run_async(self.web_research.research(query, limit=5))
        context = build_web_research_context(results)
        assistant_prompt = build_web_research_answer_prompt(query, context)
        request = AIRequest(prompt=assistant_prompt, model=self.config.settings.ai_model)
        response = self._run_async(self.ai_provider.complete(request))
        if not isinstance(response, AIResponse):
            raise CommandError("AI provider returned invalid data.")
        return CommandResult(_format_ai_response(response))

    def _local_web(self, args: list[str]) -> CommandResult:
        from fincli.app.web.manager import WebServerManager

        manager = WebServerManager(self.config)
        action = args[0].lower() if args else "status"
        try:
            if action == "start":
                status = manager.start()
            elif action == "stop":
                stopped = manager.stop()
                message = "Local web server stopped." if stopped else "Local web server is not running."
                return CommandResult(Panel(message, title="FinCLI Web"))
            elif action == "restart":
                status = manager.restart()
            elif action == "open":
                return CommandResult(Panel(f"Opened {manager.open()}", title="FinCLI Web"))
            elif action == "token" and len(args) > 1 and args[1].lower() == "rotate":
                token = manager.rotate_token()
                self.audit_log.record("web_token_rotate", "Local web token rotated")
                return CommandResult(
                    Panel(
                        f"New local access token:\n{token}\n\nStore this token securely.",
                        title="FinCLI Web Token",
                        border_style="yellow",
                    )
                )
            elif action == "logs":
                return CommandResult(Panel(manager.logs(), title="FinCLI Web Logs"))
            elif action == "config":
                if len(args) >= 4 and args[1].lower() == "set":
                    manager.set_config(args[2], " ".join(args[3:]))
                    warning = (
                        "\nWARNING: Public binding exposes FinCLI to your network."
                        if args[2] == "host" and args[3] == "0.0.0.0"
                        else ""
                    )
                    return CommandResult(
                        Panel(
                            f"Web setting {args[2]} updated.{warning}",
                            title="FinCLI Web Config",
                            border_style="yellow" if warning else "green",
                        )
                    )
                body = "\n".join(f"{key}: {value}" for key, value in manager.config_dict().items())
                return CommandResult(Panel(body, title="FinCLI Web Config"))
            else:
                status = manager.status()
        except (ImportError, RuntimeError) as exc:
            message = f'{exc}\nInstall with: pip install -e ".[web]"'
            return CommandResult(Panel(message, title="FinCLI Web", border_style="red"), status="error")
        except (OSError, ValueError) as exc:
            return CommandResult(Panel(str(exc), title="FinCLI Web", border_style="red"), status="error")
        state = "running" if status["running"] else "stopped"
        warning = "\nWARNING: Server is bound beyond localhost." if status["host"] == "0.0.0.0" else ""
        body = f"Status: {state}\nURL: {status['url']}\nHost: {status['host']}:{status['port']}\nAuthentication: {'required' if status['auth'] else 'disabled'}\nUptime: {status['uptime_seconds']}s\nUse /web token rotate to generate a new access token.{warning}"
        return CommandResult(
            Panel(body, title="FinCLI Local Web", border_style="green" if status["running"] else "yellow")
        )
