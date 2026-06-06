from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.console import Console

from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.tui.components import format_ai_message, format_thinking_message, format_user_message
from fincli.app.utils.formatting import AIResponseView
from fincli.app.tui.layout import FinCLIApp

import pytest


class FakeAIProvider:
    name = "fake-ai"

    async def complete(self, request: AIRequest) -> AIResponse:
        return AIResponse(provider=self.name, model=request.model, content="Echo response")


def test_ai_chat_render_helpers_match_terminal_style() -> None:
    user_message = format_user_message("hello")
    ai_message = format_ai_message("1. **complexity** matters")

    assert isinstance(user_message, Panel)
    assert user_message.padding == (0, 1)
    assert "hello" in str(user_message.renderable)
    assert "Thinking" in str(format_thinking_message("routing to AI assistant"))
    assert isinstance(ai_message, Markdown)


def test_ai_response_view_renders_markdown_without_raw_markers() -> None:
    response = AIResponse(
        provider="fake-ai",
        model="test-model",
        content="**Ringkasan**\n- _Poin penting_\n- Dampak pasar",
    )
    console = Console(width=80, record=True, force_terminal=False)

    console.print(AIResponseView(response))
    rendered = console.export_text()

    assert "**Ringkasan**" not in rendered
    assert "_Poin penting_" not in rendered
    assert "Ringkasan" in rendered
    assert "Poin penting" in rendered


def test_user_message_keeps_plain_text_compact() -> None:
    renderable = format_user_message("are you fast").renderable

    assert isinstance(renderable, Text)
    assert "> are you fast" in renderable.plain


@pytest.mark.anyio
async def test_plain_input_is_treated_as_ai_chat(monkeypatch) -> None:
    app = FinCLIApp()

    async with app.run_test(size=(120, 40)) as pilot:
        app.router.ai_provider = FakeAIProvider()
        command_input = app.query_one("#command_input")
        command_input.value = "hello"

        await pilot.press("enter")
        await pilot.pause()

        assert "ai chat" in str(app.query_one("#status_bar").render())
