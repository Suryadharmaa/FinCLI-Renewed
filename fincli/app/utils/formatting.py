"""Small formatting helpers."""

from __future__ import annotations

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import Markdown
from rich.text import Text

from fincli.app.providers.ai.base import AIResponse


def mask_secret(value: str | None) -> str:
    """Mask API keys and tokens before displaying them."""
    if not value:
        return "not set"
    if len(value) <= 8:
        return "set"
    return f"{value[:4]}...{value[-4:]}"


def normalize_symbol(symbol: str) -> str:
    """Normalize user-entered market symbols."""
    return symbol.strip().upper()


class AIResponseView:
    """Renderable AI response that preserves Markdown formatting in Rich/Textual."""

    def __init__(self, response: AIResponse) -> None:
        self.response = response

    def __str__(self) -> str:
        return (
            f"Provider: {self.response.provider}\n"
            f"Model: {self.response.model}\n"
            f"Response:\n{self.response.content}"
        )

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        header = Text()
        header.append("Provider: ", style="bold cyan")
        header.append(self.response.provider, style="white")
        header.append("  Model: ", style="bold cyan")
        header.append(self.response.model, style="white")
        yield header
        yield Markdown(self.response.content)


class MarkdownBlock:
    """Small renderable block for titled Markdown content."""

    def __init__(self, title: str, body: object, footer: str | None = None) -> None:
        self.title = title
        self.body = body
        self.footer = footer

    def __str__(self) -> str:
        parts = [self.title, str(self.body)]
        if self.footer:
            parts.append(self.footer)
        return "\n".join(parts)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield Text(self.title, style="bold cyan")
        yield self.body
        if self.footer:
            yield Text(self.footer, style="dim")
