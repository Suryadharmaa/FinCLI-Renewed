"""Textual layout for FinCLI."""

from __future__ import annotations

from collections.abc import Iterable
from threading import Lock

from textual.app import App, ComposeResult, SystemCommand
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.worker import Worker, WorkerState
from textual.widgets import Input, RichLog, Static

from fincli import __version__
from fincli.app.cli.autocomplete import SlashAutocomplete
from fincli.app.cli.commands import CommandRegistry
from fincli.app.cli.router import CommandResult, CommandRouter
from fincli.app.providers.ai.manager import AIProviderManager
from fincli.app.tui.components import CommandPalette, WorkingIndicator, working_verb
from fincli.app.tui.components import format_user_message, write_output_entry
from fincli.app.tui.market_provider_selector import MarketProviderSelectorScreen
from fincli.app.tui.model_selector import AIModelSelectorScreen
from fincli.app.tui.theme import APP_CSS


class FinCLIApp(App[None]):
    """Modern terminal dashboard for FinCLI v0.1."""

    CSS = APP_CSS
    TITLE = f"FinCLI v{__version__}"
    SUB_TITLE = "Financial terminal MVP"
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_output", "Clear"),
        ("escape", "interrupt", "Interrupt"),
        ("f1", "help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.registry = CommandRegistry()
        self.autocomplete = SlashAutocomplete(self.registry)
        self.router = CommandRouter(registry=self.registry)
        self._route_lock = Lock()
        self._worker_index = 0
        self._latest_worker_sequence = 0
        self._worker_meta: dict[str, dict[str, str | bool]] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace"):
            with Vertical(id="output_frame"):
                yield RichLog(id="output", wrap=True, markup=True, highlight=True)
        yield WorkingIndicator(id="working")
        yield Static("ready | /research AAPL --quick | /analyze XAUUSD | /provider status", id="status_bar")
        with Vertical(id="command_area"):
            yield Static("Type a question for AI chat, or / for commands.", id="command_hint")
            with Horizontal(id="command_line"):
                yield Static("> ", id="command_prompt")
                yield Input(placeholder="Ask FinCLI or type /help", id="command_input")
            with VerticalScroll(id="command_palette_scroll"):
                yield CommandPalette(id="command_palette")

    def on_mount(self) -> None:
        palette = self.query_one(CommandPalette)
        palette.clear_palette()
        self.query_one("#command_palette_scroll", VerticalScroll).styles.display = "none"
        output = self.query_one("#output", RichLog)
        write_output_entry(output, f"[bold]FinCLI[/] [#7a7a7a]v{__version__}[/]")
        write_output_entry(output, "[#7a7a7a]Welcome back. Type [/][#d97757]/[/][#7a7a7a] for commands.[/]")
        self._submit_route("/dashboard", display_raw="/dashboard")
        self.query_one("#command_input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        palette = self.query_one(CommandPalette)
        palette_scroll = self.query_one("#command_palette_scroll", VerticalScroll)
        value = event.value.strip()
        if not value.startswith("/"):
            palette.clear_palette()
            palette_scroll.styles.display = "none"
            return

        suggestions = self.autocomplete.suggestions_for(value)
        palette_scroll.styles.display = "block"
        palette_scroll.scroll_home(animate=False)
        palette.render_commands(suggestions, value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.input.value = ""
        palette = self.query_one(CommandPalette)
        palette.clear_palette()
        self.query_one("#command_palette_scroll", VerticalScroll).styles.display = "none"
        raw = event.value.strip()
        output = self.query_one("#output", RichLog)
        status = self.query_one("#status_bar", Static)
        if raw.lower() == "/ai_model":
            self.push_screen(AIModelSelectorScreen(self.router.config, self._set_ai_model_from_selector))
            status.update("selecting ai model | esc to close")
            return
        if raw.lower() == "/news_model":
            self.push_screen(MarketProviderSelectorScreen(self.router.config, self._set_market_provider_from_selector))
            status.update("selecting market/news provider | esc to close")
            return

        if raw and (not raw.startswith("/") or raw.lower().startswith("/ai ")):
            prompt = raw[4:].strip() if raw.lower().startswith("/ai ") else raw
            self._handle_ai_chat(prompt)
            return

        if raw.lower() == "/clear":
            self._invalidate_pending_workers()
            self.query_one(WorkingIndicator).stop()
            output.clear()
            status.update("cleared | /help untuk command")
            return
        if raw.lower() == "/exit":
            self.exit()
            return

        self._submit_route(raw, display_raw=raw)

    def action_clear_output(self) -> None:
        self._invalidate_pending_workers()
        self.query_one(WorkingIndicator).stop()
        self.query_one("#output", RichLog).clear()
        self.query_one("#status_bar", Static).update("cleared | /help untuk command")

    def action_interrupt(self) -> None:
        # Thread workers cannot be force-killed mid-call; this abandons their
        # result and stops the animation, matching the _invalidate_pending_workers
        # pattern. Selector screens use esc-to-close via their own push_screen flow.
        self.workers.cancel_group(self, "router")
        self._invalidate_pending_workers()
        self.query_one(WorkingIndicator).stop()
        self.query_one("#status_bar", Static).update("interrupted | esc")

    def action_help(self) -> None:
        output = self.query_one("#output", RichLog)
        write_output_entry(output, self.router.route("/help").renderable)

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Return a curated command palette for FinCLI."""
        yield SystemCommand(
            "Keys",
            "Show or hide FinCLI keyboard shortcuts.",
            self._toggle_help_panel,
        )
        yield SystemCommand(
            "Maximize Panel",
            "Maximize the active FinCLI panel.",
            screen.action_maximize,
        )
        yield SystemCommand(
            "Save Screenshot",
            "Save the current FinCLI screen as an SVG file.",
            lambda: self.set_timer(0.1, self.deliver_screenshot),
        )
        yield SystemCommand(
            "Change Theme",
            "Open Textual theme selector for the terminal UI.",
            self.action_change_theme,
        )
        yield SystemCommand(
            "Clear Output",
            "Clear the main output log.",
            self.action_clear_output,
        )
        yield SystemCommand(
            "Quit FinCLI",
            "Exit FinCLI and return to the terminal.",
            self.action_quit,
        )

    def _toggle_help_panel(self) -> None:
        if self.screen.query("HelpPanel"):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()

    def _set_ai_model_from_selector(self, provider: str, model: str) -> None:
        self.router.ai_provider = AIProviderManager().create(provider)
        output = self.query_one("#output", RichLog)
        status = self.query_one("#status_bar", Static)
        write_output_entry(output, f"AI model aktif: {provider} / {model}")
        status.update(f"ready | ai model: {provider}/{model}")

    def _set_market_provider_from_selector(self, providers: tuple[str, ...]) -> None:
        self.router._refresh_market_service()
        self.router.cache.clear()
        output = self.query_one("#output", RichLog)
        status = self.query_one("#status_bar", Static)
        write_output_entry(output, f"Provider market/news priority aktif: {', '.join(providers)}")
        status.update(f"ready | market provider: {providers[0] if providers else 'yfinance'}")

    def _handle_ai_chat(self, prompt: str) -> None:
        output = self.query_one("#output", RichLog)
        write_output_entry(output, format_user_message(prompt))
        self._submit_route(f"/ai {prompt}", display_raw="/ai", chat=True)

    def _submit_route(
        self,
        raw: str,
        *,
        display_raw: str,
        chat: bool = False,
        clear_output_before_result: bool = False,
    ) -> None:
        """Run a router command without blocking Textual's UI thread."""
        self._worker_index += 1
        worker_name = f"route-{self._worker_index}"
        self._latest_worker_sequence = self._worker_index
        self._worker_meta[worker_name] = {
            "raw": raw,
            "display_raw": display_raw,
            "chat": chat,
            "clear_output_before_result": clear_output_before_result,
            "sequence": str(self._worker_index),
        }
        self.query_one("#status_bar", Static).update(f"running | {display_raw}")
        self.query_one(WorkingIndicator).start(working_verb(raw))
        self.run_worker(
            lambda: self._route_in_worker(raw),
            name=worker_name,
            group="router",
            description=display_raw,
            thread=True,
        )

    def _invalidate_pending_workers(self) -> None:
        self._latest_worker_sequence = max(self._latest_worker_sequence, self._worker_index) + 1

    def _route_in_worker(self, raw: str) -> CommandResult:
        with self._route_lock:
            return self.router.route(raw)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        meta = self._worker_meta.get(worker.name or "")
        if meta is None:
            return
        if event.state not in {WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED}:
            return

        self._worker_meta.pop(worker.name or "", None)
        sequence = int(str(meta.get("sequence", "0")))
        if sequence < self._latest_worker_sequence:
            # A newer worker owns the spinner; let it keep animating.
            return
        self.query_one(WorkingIndicator).stop()
        try:
            output = self.query_one("#output", RichLog)
            status = self.query_one("#status_bar", Static)
        except NoMatches:
            return
        display_raw = str(meta["display_raw"])

        if event.state == WorkerState.CANCELLED:
            status.update(f"cancelled | {display_raw}")
            return
        if event.state == WorkerState.ERROR:
            write_output_entry(output, f"Error menjalankan {display_raw}: {worker.error}")
            status.update(f"error | {display_raw}")
            return

        result = worker.result
        if bool(meta.get("clear_output_before_result")):
            output.clear()
        if result.clear:
            output.clear()
        elif result.renderable:
            write_output_entry(output, result.renderable)

        if bool(meta.get("chat")):
            status.update(f"{result.status} | ai chat")
        else:
            status.update(f"{result.status} | last: {display_raw or 'empty'}")
        if result.should_exit:
            self.exit()
