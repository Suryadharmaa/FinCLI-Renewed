"""Reusable TUI components."""

from __future__ import annotations

from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from fincli.app.cli.commands import CommandSpec


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
                command_text = f"[black on cyan]> {command.name}[/]"
                description = f"[black on cyan]{command.description}[/]"
            table.add_row(command_text, description)

        if len(commands) > 6:
            table.add_row("[bright_black]v more[/]", "[bright_black]Ketik command lebih spesifik[/]")

        title = f"[cyan]>[/] {query or '/'}"
        self.update(Panel(table, title=title, border_style="bright_black", padding=(0, 1)))

    def clear_palette(self) -> None:
        self.update("")


def format_user_message(message: str) -> Panel:
    text = Text()
    text.append("> ", style="bold cyan")
    text.append(message, style="bold white")
    return Panel(text, border_style="#2f332f", style="on #2b2f2b", padding=(0, 1))


def format_thinking_message(message: str) -> Text:
    text = Text()
    text.append("> Thinking: ", style="dim")
    text.append(message, style="italic dim")
    return text


def format_ai_message(message: str) -> Markdown:
    return Markdown(message)
