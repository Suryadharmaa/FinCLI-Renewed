"""Lightweight web research service for AI assistance."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
import defusedxml.ElementTree as ElementTree

import httpx

from fincli.app.utils.errors import ProviderError


@dataclass(frozen=True, slots=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str = ""
    content: str = ""


class WebResearchService:
    """Search and fetch public web pages without browser automation."""

    def __init__(self, client: httpx.AsyncClient | None = None, timeout_seconds: float = 6.0) -> None:
        self._client = client
        self._owns_client = client is None
        self.timeout_seconds = timeout_seconds
        self._loop_id: int | None = None  # Track which event loop owns the client

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create and reuse HTTP client.

        Recreates client if event loop changed (handles multiple _run_async calls).
        """
        if not self._owns_client:
            if self._client is None:
                raise ProviderError("Web research client tidak tersedia.")
            return self._client

        try:
            current_loop = asyncio.get_running_loop()
            current_id = id(current_loop)
        except RuntimeError:
            current_id = None

        # Recreate client if loop changed or client doesn't exist
        if self._client is None or (current_id is not None and current_id != self._loop_id):
            if self._client is not None:
                await self._client.aclose()
                self._client = None
            self._client = httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                headers={
                    "User-Agent": "FinCLI/0.1 web research (+https://www.npmjs.com/package/@drico2008/fincli)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
                },
            )
            self._owns_client = True
            self._loop_id = current_id
        return self._client

    async def close(self) -> None:
        """Close the HTTP client if owned."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
            self._loop_id = None

    async def research(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        normalized = query.strip()
        if not normalized:
            return []
        search_results = await self.search(normalized, limit=limit)
        enriched: list[WebSearchResult] = []
        for result in search_results[:limit]:
            content = await self.fetch_text(result.url)
            enriched.append(
                WebSearchResult(
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    content=content,
                )
            )
        return enriched

    async def search(self, query: str, limit: int = 5) -> list[WebSearchResult]:
        errors: list[str] = []
        for searcher in (self._search_duckduckgo, self._search_google_news):
            try:
                results = await searcher(query, limit)
            except ProviderError as exc:
                errors.append(str(exc))
                continue
            if results:
                return results
        detail = "\n".join(f"- {error}" for error in errors) if errors else "Tidak ada hasil publik."
        raise ProviderError(
            "Semua web search provider gagal atau kosong.",
            f"{detail}\nCoba ulangi, sederhanakan query, atau cek koneksi/DNS.",
        )

    async def _search_duckduckgo(self, query: str, limit: int) -> list[WebSearchResult]:
        html = await self._get_text(f"https://duckduckgo.com/html/?q={quote_plus(query)}")
        parser = _DuckDuckGoParser()
        parser.feed(html)
        results: list[WebSearchResult] = []
        seen: set[str] = set()
        for item in parser.results:
            target = _clean_duckduckgo_url(item.url)
            if not target or target in seen:
                continue
            seen.add(target)
            results.append(WebSearchResult(title=_clean_text(item.title), url=target, snippet=_clean_text(item.snippet)))
            if len(results) >= limit:
                break
        return results

    async def _search_google_news(self, query: str, limit: int) -> list[WebSearchResult]:
        rss = await self._get_text(f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=id&gl=ID&ceid=ID:id")
        try:
            root = ElementTree.fromstring(rss)
        except ElementTree.ParseError as exc:
            raise ProviderError("Google News RSS tidak valid.") from exc

        results: list[WebSearchResult] = []
        seen: set[str] = set()
        for item in root.findall(".//item"):
            title = _clean_text(item.findtext("title") or "")
            url = _clean_text(item.findtext("link") or "")
            snippet = _clean_text(_html_to_text(item.findtext("description") or ""))
            if not title or not url or url in seen:
                continue
            seen.add(url)
            results.append(WebSearchResult(title=title, url=url, snippet=snippet))
            if len(results) >= limit:
                break
        return results

    async def fetch_text(self, url: str, max_chars: int = 2400) -> str:
        if not url.startswith(("http://", "https://")):
            return ""
        try:
            html = await self._get_text(url)
        except ProviderError:
            return ""
        text = _html_to_text(html)
        return text[:max_chars]

    async def _get_text(self, url: str) -> str:
        client = await self._get_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.TimeoutException as exc:
            raise ProviderError("Web research timeout.", f"URL: {url}") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Web research gagal: HTTP {exc.response.status_code}.", f"URL: {url}") from exc
        except httpx.RequestError as exc:
            raise ProviderError(f"Web research gagal terhubung: {exc}.", f"URL: {url}") from exc


def should_use_web_research(prompt: str) -> bool:
    """Detect prompts that benefit from current public web context."""
    normalized = prompt.lower()
    keywords = (
        "terkini",
        "terbaru",
        "hari ini",
        "sekarang",
        "saat ini",
        "update",
        "berita",
        "news",
        "web",
        "search",
        "cari",
        "penyebab",
        "mengapa",
        "kenapa",
        "rupiah",
        "inflasi",
        "suku bunga",
        "bank indonesia",
        "fed",
        "dollar",
        "dolar",
        "yield",
        "minyak",
        "emas",
    )
    return any(keyword in normalized for keyword in keywords)


def build_web_research_context(results: list[WebSearchResult]) -> str:
    if not results:
        return "Web Research: no public web context returned."
    sections = ["Web Research Context:"]
    for index, result in enumerate(results, start=1):
        sections.extend(
            [
                f"{index}. {result.title}",
                f"URL: {result.url}",
                f"Snippet: {result.snippet or 'N/A'}",
                f"Extract: {result.content or 'N/A'}",
            ]
        )
    return "\n".join(sections)


class _DuckResult:
    def __init__(self) -> None:
        self.title = ""
        self.url = ""
        self.snippet = ""


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[_DuckResult] = []
        self._current: _DuckResult | None = None
        self._capture: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = attr.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._current = _DuckResult()
            self._current.url = attr.get("href", "") or ""
            self._capture = "title"
            self._buffer = []
        elif self._current is not None and tag in {"a", "div"} and "result__snippet" in classes:
            self._capture = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._current is None or self._capture is None:
            return
        if self._capture == "title" and tag == "a":
            self._current.title = _clean_text(" ".join(self._buffer))
            self._capture = None
            self._buffer = []
        elif self._capture == "snippet" and tag in {"a", "div"}:
            self._current.snippet = _clean_text(" ".join(self._buffer))
            self.results.append(self._current)
            self._current = None
            self._capture = None
            self._buffer = []


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            cleaned = _clean_text(data)
            if cleaned:
                self.parts.append(cleaned)


def _html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return _clean_text(" ".join(extractor.parts))


def _clean_text(value: str) -> str:
    text = unescape(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target)
    return url
