import pytest

from fincli.app.tui.layout import FinCLIApp


@pytest.mark.anyio
async def test_system_commands_are_fincli_specific_and_clean() -> None:
    app = FinCLIApp()

    async with app.run_test(size=(120, 40)):
        commands = list(app.get_system_commands(app.screen))
        titles = [command.title for command in commands]
        help_text = " ".join(command.help for command in commands)

        assert "Keys" in titles
        assert "Maximize Panel" in titles
        assert "Save Screenshot" in titles
        assert "Change Theme" in titles
        assert "Screenshot" not in titles
        assert "Theme" not in titles
        assert "Maximize" not in titles
        assert "amximize" not in help_text.lower()
        assert "focused widget" not in help_text.lower()
