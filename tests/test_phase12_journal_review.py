from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class JournalAIProvider:
    name = "journal-ai"

    def __init__(self) -> None:
        self.last_prompt = ""

    async def complete(self, request: AIRequest) -> AIResponse:
        self.last_prompt = request.prompt
        return AIResponse(provider=self.name, model=request.model, content="Review: reduce revenge trading and improve exit rules.")


def make_router(tmp_path: Path, ai: JournalAIProvider | None = None) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        ai_provider=ai or JournalAIProvider(),
    )


def render_text(renderable) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def seed_journal(router: CommandRouter) -> None:
    router.journal.add("AAPL", bias="bullish", entry_reason="breakout", result="win", emotion="calm", lesson="wait confirmation", tags="breakout,trend")
    router.journal.add("MSFT", bias="bearish", entry_reason="late short", result="loss", emotion="fear", lesson="avoid chasing", tags="mistake,late")
    router.journal.add("AAPL", bias="bullish", entry_reason="pullback", result="win", emotion="confident", lesson="follow plan", tags="pullback")


def test_journal_stats_outputs_summary(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    seed_journal(router)

    result = router.route("/journal stats")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "Journal Stats" in output
    assert "Total Entries" in output
    assert "Win Rate" in output
    assert "66.7%" in output
    assert "AAPL" in output


def test_journal_review_uses_ai_provider_with_stats_context(tmp_path: Path) -> None:
    ai = JournalAIProvider()
    router = make_router(tmp_path, ai)
    seed_journal(router)

    result = router.route("/journal review")

    output = str(result.renderable)
    assert result.status == "ready"
    assert "Review:" in output
    assert "Total Entries" in ai.last_prompt
    assert "avoid chasing" in ai.last_prompt
    assert "bukan nasihat keuangan" in output
