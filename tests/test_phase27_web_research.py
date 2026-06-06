from pathlib import Path

import httpx

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.services.web_research import WebResearchService, build_web_research_context, should_use_web_research
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class CapturingAIProvider:
    name = "capture-ai"

    def __init__(self) -> None:
        self.last_prompt = ""

    async def complete(self, request: AIRequest) -> AIResponse:
        self.last_prompt = request.prompt
        return AIResponse(provider=self.name, model=request.model, content="web context received")


def make_web_service() -> WebResearchService:
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "duckduckgo.com/html" in url:
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a class="result__a" href="https://example.com/rupiah">Rupiah melemah karena dollar menguat</a>
                  <a class="result__snippet">Bank Indonesia, dollar index, dan arus modal menekan rupiah.</a>
                </body></html>
                """,
            )
        if "example.com/rupiah" in url:
            return httpx.Response(
                200,
                text="<html><body><article>Rupiah melemah terhadap banyak mata uang karena dollar AS menguat dan yield naik.</article></body></html>",
            )
        return httpx.Response(404)

    return WebResearchService(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://duckduckgo.com"),
        timeout_seconds=2,
    )


def make_router(tmp_path: Path) -> tuple[CommandRouter, CapturingAIProvider]:
    ai = CapturingAIProvider()
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        ai_provider=ai,
    )
    router.web_research = make_web_service()
    return router, ai


def test_web_research_service_searches_and_fetches_public_context() -> None:
    service = make_web_service()
    import asyncio

    fetched = asyncio.run(service.research("penyebab rupiah melemah hari ini", limit=1))

    assert fetched[0].title == "Rupiah melemah karena dollar menguat"
    assert "dollar AS menguat" in fetched[0].content
    assert "example.com/rupiah" in build_web_research_context(fetched)


def test_should_use_web_research_detects_current_market_question() -> None:
    assert should_use_web_research("apa penyebab penurunan rupiah hari ini")
    assert should_use_web_research("berita terbaru BI rate")
    assert not should_use_web_research("halo apa kabar")


def test_web_command_outputs_result_table(tmp_path: Path) -> None:
    router, _ = make_router(tmp_path)

    result = router.route("/web sources penyebab rupiah melemah hari ini")

    assert result.status == "ready"
    assert "Web Research" in str(result.renderable.title)


def test_web_command_uses_ai_to_summarize_web_context(tmp_path: Path) -> None:
    router, ai = make_router(tmp_path)

    result = router.route("/web penyebab rupiah melemah hari ini")

    assert result.status == "ready"
    assert "web context received" in str(result.renderable)
    assert "Web Search Skill Result" in ai.last_prompt
    assert "Do not answer by only listing articles or links" in ai.last_prompt
    assert "Rupiah melemah karena dollar menguat" in ai.last_prompt


def test_web_command_handles_connection_error(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failed", request=request)

    router, _ = make_router(tmp_path)
    router.web_research = WebResearchService(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        timeout_seconds=2,
    )

    result = router.route("/web sources penyebab rupiah melemah hari ini")

    assert result.status == "error"
    assert "Semua web search provider gagal" in str(result.renderable.renderable)


def test_web_research_falls_back_to_google_news_when_duckduckgo_times_out() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "duckduckgo.com/html" in url:
            raise httpx.TimeoutException("slow search", request=request)
        if "news.google.com/rss/search" in url:
            return httpx.Response(
                200,
                text="""<?xml version="1.0" encoding="UTF-8"?>
                <rss><channel>
                  <item>
                    <title>Rupiah melemah karena dolar AS menguat</title>
                    <link>https://news.google.com/articles/example</link>
                    <description>Tekanan dolar AS dan yield global mempengaruhi rupiah.</description>
                  </item>
                </channel></rss>""",
            )
        return httpx.Response(200, text="<html><body>article text</body></html>")

    service = WebResearchService(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), timeout_seconds=2)
    import asyncio

    results = asyncio.run(service.search("kenapa rupiah melemah", limit=3))

    assert results[0].title == "Rupiah melemah karena dolar AS menguat"
    assert "news.google.com" in results[0].url


def test_ai_freechat_adds_web_context_for_current_question(tmp_path: Path) -> None:
    router, ai = make_router(tmp_path)

    result = router.route("/ai apa penyebab penurunan rupiah terhadap semua mata uang hari ini")

    assert result.status == "ready"
    assert "web context received" in str(result.renderable)
    assert "Web Research Context" in ai.last_prompt
    assert "Rupiah melemah karena dollar menguat" in ai.last_prompt
    assert "https://example.com/rupiah" in ai.last_prompt
