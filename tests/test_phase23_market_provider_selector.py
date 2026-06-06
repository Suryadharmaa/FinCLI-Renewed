import pytest

from fincli.app.tui.layout import FinCLIApp
from fincli.app.tui.market_provider_selector import (
    market_provider_choices,
    priority_presets,
    recommended_provider_priority,
)


def test_market_provider_selector_catalog_and_priority_presets() -> None:
    providers = {choice.provider for choice in market_provider_choices()}

    assert {"yfinance", "finnhub", "twelvedata", "custom"}.issubset(providers)
    assert recommended_provider_priority("finnhub")[0] == "finnhub"
    assert recommended_provider_priority("finnhub")[-1] == "yfinance"
    assert recommended_provider_priority("yfinance") == ("yfinance",)

    presets = priority_presets("twelvedata")
    labels = {preset.label for preset in presets}
    assert "Recommended fallback" in labels
    assert any(preset.providers == ("yfinance",) for preset in presets)


@pytest.mark.anyio
async def test_news_model_command_opens_market_provider_selector() -> None:
    app = FinCLIApp()

    async with app.run_test(size=(120, 40)) as pilot:
        command_input = app.query_one("#command_input")
        command_input.value = "/news_model"

        await pilot.press("enter")
        await pilot.pause()

        assert app.screen.query_one("#ai_selector_title").render() == "Select Market/News Provider"
        assert "Finnhub" in str(app.screen.query_one("#ai_selector_list").render())
        assert "Twelve Data" in str(app.screen.query_one("#ai_selector_list").render())
