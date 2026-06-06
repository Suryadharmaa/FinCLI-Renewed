from __future__ import annotations

import time

import pytest
from rich.panel import Panel

from fincli.app.cli.router import CommandResult
from fincli.app.tui.layout import FinCLIApp


class SlowRouter:
    def route(self, raw: str) -> CommandResult:
        time.sleep(0.8)
        return CommandResult(Panel(f"done {raw}"), status="ready")


@pytest.mark.anyio
async def test_tui_routes_commands_without_blocking_ui_thread() -> None:
    app = FinCLIApp()

    async with app.run_test(size=(120, 40)) as pilot:
        app.router = SlowRouter()  # type: ignore[assignment]
        command_input = app.query_one("#command_input")
        command_input.value = "/quote AAPL"

        started = time.perf_counter()
        await pilot.press("enter")
        elapsed = time.perf_counter() - started

        assert elapsed < 0.5
        assert "running | /quote AAPL" in str(app.query_one("#status_bar").render())

        await pilot.pause(1.0)

        assert "ready | last: /quote AAPL" in str(app.query_one("#status_bar").render())


@pytest.mark.anyio
async def test_tui_routes_ai_chat_without_blocking_ui_thread() -> None:
    app = FinCLIApp()

    async with app.run_test(size=(120, 40)) as pilot:
        app.router = SlowRouter()  # type: ignore[assignment]
        command_input = app.query_one("#command_input")
        command_input.value = "hello"

        started = time.perf_counter()
        await pilot.press("enter")
        elapsed = time.perf_counter() - started

        assert elapsed < 0.5
        assert "running | /ai" in str(app.query_one("#status_bar").render())

        await pilot.pause(1.0)

        assert "ready | ai chat" in str(app.query_one("#status_bar").render())


@pytest.mark.anyio
async def test_clear_invalidates_pending_route_output() -> None:
    app = FinCLIApp()

    async with app.run_test(size=(120, 40)) as pilot:
        app.router = SlowRouter()  # type: ignore[assignment]
        command_input = app.query_one("#command_input")
        command_input.value = "/quote AAPL"

        await pilot.press("enter")
        await pilot.pause(0.1)

        command_input.value = "/clear"
        await pilot.press("enter")
        await pilot.pause(1.0)

        assert "cleared | /help untuk command" in str(app.query_one("#status_bar").render())
