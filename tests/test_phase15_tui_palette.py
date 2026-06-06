import pytest
from textual.containers import VerticalScroll

from fincli.app.tui.components import CommandPalette
from fincli.app.tui.layout import FinCLIApp


@pytest.mark.anyio
async def test_tui_uses_inline_command_palette_without_sidebar() -> None:
    app = FinCLIApp()

    async with app.run_test(size=(120, 40)) as pilot:
        assert len(list(app.query("#sidebar"))) == 0
        assert len(list(app.query("#command_line"))) == 1
        scroll = app.query_one("#command_palette_scroll", VerticalScroll)
        palette = app.query_one(CommandPalette)
        assert scroll.styles.display == "none"

        await pilot.click("#command_input")
        await pilot.press("/")

        assert scroll.styles.display == "block"
        assert len(app.autocomplete.suggestions_for("/")) > 8
