"""Local document retrieval with page-level evidence and bounded PDF extraction."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fincli.app.workspace.models import Instrument, result

if TYPE_CHECKING:
    from fincli.app.workspace.store import WorkspaceStore

MAX_BYTES = 8 * 1024 * 1024
MAX_TEXT = 1_500_000
MAX_PAGES = 400


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,}", text.lower())


class DocumentService:
    def __init__(self, store: WorkspaceStore):
        self.store = store

    def import_file(self, path: str, symbol: str = "") -> dict[str, Any]:
        file = Path(path).expanduser().resolve()
        if not file.is_file() or file.stat().st_size > MAX_BYTES:
            raise ValueError("Choose a PDF, TXT or Markdown file of at most 8 MiB.")
        return self.import_bytes(file.name, file.read_bytes(), symbol)

    def import_bytes(self, title: str, content: bytes, symbol: str = "") -> dict[str, Any]:
        if len(content) > MAX_BYTES or not content:
            raise ValueError("Document must contain 1 byte to 8 MiB.")
        symbol = Instrument.parse(symbol).symbol if symbol.strip() else ""
        title = Path(title.replace("\\", "/")).name[:160]
        extension = Path(title).suffix.lower()
        if extension == ".pdf":
            from pypdf import PdfReader

            try:
                reader = PdfReader(io.BytesIO(content))
                if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
                    raise ValueError("Encrypted or over-400-page PDFs are unsupported.")
                pages = []
                total = 0
                for page in reader.pages:
                    text = page.extract_text() or ""
                    total += len(text)
                    if total > MAX_TEXT:
                        raise ValueError("Extracted text exceeds 1.5 million characters.")
                    pages.append(text)
            except ValueError:
                raise
            except Exception as exc:  # noqa: BLE001 - corrupt PDF must produce a useful validation error
                raise ValueError("Unable to extract PDF text.") from exc
        elif extension in {".txt", ".md"}:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Text documents must use UTF-8.") from exc
            pages = text.split("\f")
        else:
            raise ValueError("Supported documents: PDF, TXT, MD.")
        if len(pages) > MAX_PAGES or sum(map(len, pages)) > MAX_TEXT:
            raise ValueError("Document exceeds extraction limits.")
        if not any(p.strip() for p in pages):
            raise ValueError("Document has no extractable text. Scanned PDFs require OCR first.")
        digest = hashlib.sha256(content).hexdigest()
        existing = self.store.db.query(
            "SELECT id FROM workspace_documents WHERE digest=? AND symbol=?", (digest, symbol)
        )
        doc_id = existing[0]["id"] if existing else uuid.uuid4().hex
        self.store.db.execute(
            "INSERT OR REPLACE INTO workspace_documents(id,title,symbol,digest,pages) VALUES (?,?,?,?,?)",
            (doc_id, title, symbol, digest, json.dumps(pages)),
        )
        return result(
            "document_import", {"id": doc_id, "title": title, "symbol": symbol, "pages": len(pages), "digest": digest}
        )

    def list(self, symbol: str = "") -> list[dict[str, Any]]:
        if symbol:
            symbol = Instrument.parse(symbol).symbol
        return [
            dict(r)
            for r in self.store.db.query(
                "SELECT id,title,symbol,digest,created_at FROM workspace_documents WHERE (?='' OR symbol=?) ORDER BY created_at DESC",
                (symbol, symbol),
            )
        ]

    def page(self, doc_id: str, page: int) -> dict[str, Any]:
        rows = self.store.db.query("SELECT title,pages FROM workspace_documents WHERE id=?", (doc_id,))
        if not rows:
            raise ValueError("Document not found.")
        pages = json.loads(rows[0]["pages"])
        if not 1 <= page <= len(pages):
            raise ValueError("Page is outside document range.")
        return {"document_id": doc_id, "title": rows[0]["title"], "page": page, "text": pages[page - 1]}

    def search(self, query: str, symbol: str = "", limit: int = 8) -> dict[str, Any]:
        if not query.strip() or len(query) > 2000:
            raise ValueError("Enter a query of 1-2000 characters.")
        symbol = Instrument.parse(symbol).symbol if symbol else ""
        tokens = set(words(query))
        candidates = []
        docs = self.store.db.query(
            "SELECT * FROM workspace_documents WHERE (?='' OR symbol=?) ORDER BY created_at DESC LIMIT 50",
            (symbol, symbol),
        )
        for doc in docs:
            for page_no, text in enumerate(json.loads(doc["pages"]), 1):
                for offset in range(0, len(text), 900):
                    chunk = text[offset : offset + 1200]
                    w = words(chunk)
                    score = sum(math.log1p(w.count(t)) for t in tokens) / math.sqrt(max(1, len(w)))
                    if score:
                        candidates.append(
                            {
                                "document_id": doc["id"],
                                "title": doc["title"],
                                "page": page_no,
                                "quote": chunk,
                                "offset": offset,
                                "score": round(score, 6),
                                "digest": doc["digest"],
                            }
                        )
        hits = sorted(candidates, key=lambda c: c["score"], reverse=True)[: max(1, min(limit, 20))]
        for i, hit in enumerate(hits, 1):
            hit["citation_id"] = f"D{i}"
        return result(
            "document_evidence",
            {
                "query": query,
                "evidence": hits,
                "retrieval": "lexical; inspect original page",
                "documents_searched": len(docs),
            },
            status="ok" if hits else "partial",
            warnings=[] if hits else ["No matching evidence. Broaden the query or import relevant documents."],
        )
