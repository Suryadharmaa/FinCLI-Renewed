"""Structured adapter from the terminal command router to Local Web Access."""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fincli.app.utils.formatting import AIResponseView, MarkdownBlock
from fincli.app.web.security import command_requires_confirmation

if TYPE_CHECKING:
    from fincli.app.cli.router import CommandRouter

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
BOX_DRAWING_RE = re.compile(r"[╭╮╯╰─│┌┐└┘├┤┬┴┼═║╔╗╚╝]|(?:â[•”][^\s]?)+")
TERMINAL_ONLY_SECRET_COMMANDS = ("/ai_model key", "/notification add")


class OutputMode(StrEnum):
    TERMINAL = "terminal"
    WEB = "web"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class CommandExecutionContext:
    output_mode: OutputMode = OutputMode.WEB
    source: Literal["cli", "web"] = "web"
    user_confirmed: bool = False


@dataclass(slots=True)
class WebTable:
    title: str | None
    columns: list[str]
    rows: list[list[str]]
    caption: str | None = None


@dataclass(slots=True)
class WebCard:
    title: str
    value: str = ""
    detail: str = ""
    tone: str = "neutral"


@dataclass(slots=True)
class WebError:
    message: str
    title: str = "Command failed"
    code: str | None = None
    provider: str | None = None
    suggestion: str | None = None


@dataclass(slots=True)
class WebCommandResult:
    ok: bool
    kind: str
    command: str
    status: str
    title: str | None = None
    summary: str | None = None
    message: str | None = None
    markdown: str | None = None
    text: str | None = None
    tables: list[WebTable] = field(default_factory=list)
    cards: list[WebCard] = field(default_factory=list)
    errors: list[WebError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content(self) -> str:
        """Compatibility value for persisted messages and SSE clients."""
        return self.markdown or self.text or self.message or self.summary or ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text or "")


def looks_like_terminal_box(text: str) -> bool:
    return len(BOX_DRAWING_RE.findall(text or "")) >= 4


def sanitize_web_text(text: str) -> str:
    clean = strip_ansi(text or "")
    if looks_like_terminal_box(clean):
        clean = BOX_DRAWING_RE.sub("", clean)
    lines = [line.strip() for line in clean.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def extract_tables(renderable: object) -> list[dict[str, Any]]:
    """Compatibility helper retained for existing integrations/tests."""
    return [asdict(table) for table in _extract_tables(renderable)]


def infer_command(message: str) -> str:
    text = message.strip()
    lowered = text.lower()
    if text.startswith("/"):
        return text
    symbol = _last_symbol(text)
    if "portfolio" in lowered:
        return "/portfolio risk" if "risk" in lowered else "/portfolio"
    if "compare provider" in lowered and symbol:
        return f"/provider compare {symbol}"
    if "backtest" in lowered and symbol:
        return f"/backtest {symbol} sma_cross 1d"
    if ("analyze" in lowered or "research" in lowered) and symbol:
        return f"/research {symbol} --deep" if "deep" in lowered or "deeply" in lowered else f"/research {symbol}"
    if "scan" in lowered and "rsi" in lowered:
        return "/scan sp500 rsi<30"
    return f"/ai {text}"


def execute_command(
    router: CommandRouter,
    command: str,
    confirmed: bool = False,
    context: CommandExecutionContext | None = None,
) -> WebCommandResult:
    execution = context or CommandExecutionContext(user_confirmed=confirmed)
    normalized = " ".join(command.strip().lower().split())
    if any(normalized.startswith(prefix) for prefix in TERMINAL_ONLY_SECRET_COMMANDS):
        error = WebError(
            title="Terminal required",
            message="Commands that contain credentials cannot be submitted through Local Web Access.",
            code="TERMINAL_ONLY_SECRET",
            suggestion="Run this command in the FinCLI terminal so secret values are not stored in web or session history.",
        )
        return WebCommandResult(False, "error", command, "blocked", title=error.title, message=error.message, errors=[error])
    if normalized == "/clear":
        return WebCommandResult(True, "action", command, "ready", message="Conversation view cleared.", metadata={"action": "clear"})
    if normalized == "/exit":
        return WebCommandResult(True, "action", command, "ready", message="The browser session remains open. Close this tab to exit Local Web Access.", metadata={"action": "exit"})
    if normalized in {"/ai_model", "/news_model"}:
        target = "AI provider/model" if normalized == "/ai_model" else "market/news provider"
        return WebCommandResult(
            True,
            "settings",
            command,
            "ready",
            title=f"Select {target}",
            text="The terminal picker is not used in a browser. Use the selector in the top bar or submit this command with explicit arguments.",
            metadata={"action": "open_model_selector", "selector": normalized[1:]},
        )
    if command_requires_confirmation(command) and not execution.user_confirmed:
        error = WebError(
            title="Confirmation required",
            message="This sensitive action requires explicit confirmation.",
            code="CONFIRMATION_REQUIRED",
            suggestion="Review the action and confirm it explicitly before continuing.",
        )
        return WebCommandResult(False, "error", command, "confirmation_required", title=error.title, message=error.message, errors=[error])
    try:
        result = router.route(command)
    except Exception as exc:  # noqa: BLE001
        return error_to_web(exc, command)
    return renderable_to_web(result.renderable, command, result.status)


def renderable_to_web(renderable: object, command: str, status: str = "ready") -> WebCommandResult:
    if isinstance(renderable, AIResponseView):
        response = renderable.response
        return WebCommandResult(
            True,
            "markdown",
            command,
            status,
            title="AI response",
            markdown=sanitize_web_text(response.content),
            metadata={"provider": response.provider, "model": response.model},
        )
    if isinstance(renderable, MarkdownBlock):
        nested = renderable_to_web(renderable.body, command, status)
        nested.title = renderable.title
        if renderable.footer:
            nested.warnings.append(sanitize_web_text(renderable.footer))
        return nested
    tables = _extract_tables(renderable)
    if tables:
        return WebCommandResult(True, _command_kind(command, "table"), command, status, title=tables[0].title, tables=tables)
    if isinstance(renderable, Panel):
        message = _plain_value(renderable.renderable)
        title = sanitize_web_text(str(renderable.title or "Result"))
        if status == "error" or "error" in title.lower() or _looks_like_error(message):
            return _error_message_to_web(message, command, title)
        return WebCommandResult(True, _command_kind(command, "card"), command, status, title=title, text=message)
    if isinstance(renderable, Group):
        text = _fallback_text(renderable)
        return WebCommandResult(status != "error", _command_kind(command, "text"), command, status, text=text)
    text = _plain_value(renderable)
    if status == "error" or _looks_like_error(text):
        return _error_message_to_web(text, command)
    return WebCommandResult(True, _command_kind(command, "text"), command, status, text=text or "No displayable output.")


def error_to_web(error: Exception, command: str = "") -> WebCommandResult:
    return _error_message_to_web(str(error), command)


def _error_message_to_web(message: str, command: str, title: str = "Command failed") -> WebCommandResult:
    clean = sanitize_web_text(message) or "The command could not be completed."
    provider = _provider_from_message(clean)
    rate_limited = "rate limit" in clean.lower()
    if rate_limited and provider:
        title = f"{provider.title()} rate limited"
        clean = f"Provider {provider} is currently rate limited."
    error = WebError(
        title=title,
        message=clean,
        provider=provider,
        code="RATE_LIMITED" if rate_limited else "COMMAND_ERROR",
        suggestion=(
            "Wait a moment, switch to another model, or configure a fallback provider."
            if rate_limited
            else "Check provider status and command arguments, then try again."
        ),
    )
    return WebCommandResult(False, "error", command, "error", title=title, message=clean, errors=[error], metadata={"provider": provider} if provider else {})


def _extract_tables(renderable: object) -> list[WebTable]:
    if isinstance(renderable, Table):
        columns = [sanitize_web_text(str(column.header)) for column in renderable.columns]
        count = len(renderable.columns[0]._cells) if renderable.columns else 0
        rows = [[_plain_value(column._cells[index]) for column in renderable.columns] for index in range(count)]
        return [WebTable(_optional_text(renderable.title), columns, rows, _optional_text(renderable.caption))]
    if isinstance(renderable, Group):
        tables: list[WebTable] = []
        for child in renderable.renderables:
            tables.extend(_extract_tables(child))
        return tables
    return []


def _plain_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Text):
        return sanitize_web_text(value.plain)
    if isinstance(value, str):
        return sanitize_web_text(value)
    return sanitize_web_text(str(value))


def _fallback_text(renderable: object) -> str:
    output = io.StringIO()
    console = Console(width=120, force_terminal=False, color_system=None, file=output)
    console.print(renderable)
    return sanitize_web_text(output.getvalue())


def _optional_text(value: object) -> str | None:
    text = _plain_value(value)
    return text or None


def _looks_like_error(message: str) -> bool:
    lowered = message.lower()
    return any(term in lowered for term in ("rate limited", "failed", "invalid", "unavailable", "error:"))


def _provider_from_message(message: str) -> str | None:
    match = re.search(r"provider\s+([a-z0-9_-]+)", message, re.IGNORECASE)
    return match.group(1).lower() if match else None


def _command_kind(command: str, fallback: str) -> str:
    parts = command.lstrip("/").split()
    if not parts:
        return fallback
    return "_".join(parts[:2]) if parts[0] in {"provider", "portfolio"} and len(parts) > 1 else parts[0]


def _last_symbol(text: str) -> str:
    candidates = re.findall(r"\b[A-Z][A-Z0-9.-]{1,11}\b", text)
    ignored = {"RSI", "SP500", "CLI"}
    return next((item for item in reversed(candidates) if item not in ignored), "")
