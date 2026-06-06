import pytest

from fincli.app.tui.layout import FinCLIApp
from fincli.app.tui.model_selector import MODEL_CATALOG, PROVIDERS


@pytest.mark.anyio
async def test_ai_model_command_opens_provider_and_model_selector(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    app = FinCLIApp()

    async with app.run_test(size=(120, 40)) as pilot:
        command_input = app.query_one("#command_input")
        command_input.value = "/ai_model"

        await pilot.press("enter")
        await pilot.pause()

        assert app.screen.query_one("#ai_selector_title").render() == "Select Provider"
        assert "OpenRouter" in str(app.screen.query_one("#ai_selector_list").render())

        await pilot.press("enter")
        await pilot.pause()

        assert "already configured" in str(app.screen.query_one("#ai_selector_title").render())
        assert "Use existing configuration" in str(app.screen.query_one("#ai_selector_list").render())

        await pilot.press("enter")
        await pilot.pause()

        assert app.screen.query_one("#ai_selector_title").render() == "Select Model"
        assert "OpenRouter" in str(app.screen.query_one("#ai_selector_provider").render())


def test_ai_model_selector_has_provider_and_model_catalog() -> None:
    assert any(provider.provider == "openrouter" for provider in PROVIDERS)
    assert MODEL_CATALOG["openrouter"]
    assert any(model.model == "openai/gpt-4o-mini" for model in MODEL_CATALOG["openrouter"])
