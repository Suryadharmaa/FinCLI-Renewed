"""Reusable TUI components."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import RichLog, Static

if TYPE_CHECKING:
    from textual.timer import Timer

    from fincli.app.cli.commands import CommandSpec

# Cycling glyphs for the working animation (Claude-CLI style).
GLYPHS = ("✻", "✽", "✶", "✴")

# Map a command root to the verb shown while it runs.
_VERBS = {
    "/research": "Researching",
    "/news": "Fetching news",
    "/web": "Searching",
    "/macro": "Loading macro",
    "/calendar": "Loading calendar",
    "/analyze": "Analyzing",
    "/technical": "Analyzing",
    "/mtf": "Analyzing",
    "/scan": "Scanning",
    "/backtest": "Backtesting",
    "/market": "Fetching market",
    "/chart": "Charting",
    "/ai": "Thinking",
    "/provider": "Checking providers",
    "/notification": "Sending notification",
}


def working_verb(command: str) -> str:
    """Return the animation verb for a raw command line."""
    root = command.strip().split(maxsplit=1)[0].lower() if command.strip() else ""
    return _VERBS.get(root, "Working")


def spinner_frame(verb: str, frame_index: int, elapsed_seconds: int) -> str:
    """Render one spinner frame as Rich markup. Pure and unit-testable."""
    glyph = GLYPHS[frame_index % len(GLYPHS)]
    return f"[#d97757]{glyph}[/] {verb}… ({elapsed_seconds}s · esc to interrupt)"


class WorkingIndicator(Static):
    """Animated 'working' line shown while a router command runs."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._verb = "Working"
        self._frame = 0
        self._start: float = 0.0
        self._timer: Timer | None = None

    def start(self, verb: str) -> None:
        self._verb = verb
        self._frame = 0
        self._start = time.monotonic()
        self.display = True
        self.update(spinner_frame(self._verb, self._frame, 0))
        if self._timer is None:
            self._timer = self.set_interval(0.1, self._tick)
        else:
            self._timer.resume()

    def _tick(self) -> None:
        self._frame += 1
        elapsed = int(time.monotonic() - self._start)
        self.update(spinner_frame(self._verb, self._frame, elapsed))

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.pause()
        self.display = False
        self.update("")


class TokenCounter(Static):
    """Live token counter shown during AI streaming."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._token_count = 0
        self._start: float = 0.0

    def reset(self) -> None:
        self._token_count = 0
        self._start = time.monotonic()

    def increment(self, tokens: int = 1) -> None:
        self._token_count += tokens
        elapsed = time.monotonic() - self._start if self._start else 0
        tps = self._token_count / elapsed if elapsed > 0 else 0
        self.update(f"  tokens: {self._token_count:,} · {tps:.1f} tok/s")

    def show(self) -> None:
        self.display = True

    def hide(self) -> None:
        self.display = False
        self.update("")


class CommandPalette(Static):
    """Slash command palette shown near the command input."""

    def render_commands(self, commands: list[CommandSpec], query: str = "") -> None:
        table = Table.grid(expand=True)
        table.add_column("Command", style="white", no_wrap=True, ratio=1)
        table.add_column("Description", style="bright_black", justify="right", ratio=3)

        for index, command in enumerate(commands):
            command_text = command.name
            description = command.description
            if index == 0:
                command_text = f"[black on #d97757]> {command.name}[/]"
                description = f"[black on #d97757]{command.description}[/]"
            table.add_row(command_text, description)

        if len(commands) > 6:
            table.add_row("[bright_black]v more[/]", "[bright_black]Type a more specific command[/]")

        title = f"[#d97757]>[/] {query or '/'}"
        self.update(Panel(table, title=title, border_style="#3a3a3a", padding=(0, 1)))

    def clear_palette(self) -> None:
        self.update("")


def format_user_message(message: str) -> Panel:
    text = Text()
    text.append("> ", style="bold #d97757")
    text.append(message, style="bold white")
    return Panel(text, border_style="#3a3a3a", padding=(0, 1))


def format_thinking_message(message: str) -> Text:
    text = Text()
    text.append("> Thinking: ", style="dim")
    text.append(message, style="italic dim")
    return text


def format_ai_message(message: str) -> Markdown:
    return Markdown(message)


def write_output_entry(log: object, renderable: object) -> None:
    """Write one output entry with a single blank line separator.

    No visual barrier characters are emitted here; Rich/Textual renderables keep
    their own borders if they need one.
    """

    items = getattr(log, "items", None)
    if isinstance(items, list) and items:
        log.write("")
        log.write(renderable)
        return
    line_count = getattr(log, "line_count", 0)
    if isinstance(line_count, int) and line_count > 0:
        log.write("")
    log.write(renderable)


class StreamingOutput(RichLog):
    """Dedicated container for streaming AI output.

    Separated from the main output RichLog so that clearing the stream
    does not destroy previous conversation history.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.display = False

    def start_stream(self) -> None:
        """Show the streaming container and clear any previous content."""
        self.clear()
        self.display = True

    def update_stream(self, renderable: object) -> None:
        """Replace the current stream content (clear + rewrite)."""
        self.clear()
        self.write(renderable)

    def end_stream(self) -> None:
        """Hide the streaming container after stream completes."""
        self.clear()
        self.display = False
