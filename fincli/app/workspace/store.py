"""Additive SQLite storage for layouts, documents and reproducible experiments."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, cast

from fincli.app.workspace.models import json_safe

if TYPE_CHECKING:
    from fincli.app.storage.database import FinCLIDatabase

LAYOUTS = {
    "research": ["chart", "company", "news", "documents"],
    "trading": ["chart", "technical", "news", "watchlist"],
    "portfolio": ["portfolio", "chart", "news", "watchlist"],
    "macro": ["macro", "chart", "news", "watchlist"],
}
PANELS = {p for panels in LAYOUTS.values() for p in panels}


class WorkspaceStore:
    def __init__(self, db: FinCLIDatabase):
        self.db = db
        for statement in (
            "CREATE TABLE IF NOT EXISTS workspace_layouts (name TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE IF NOT EXISTS workspace_documents (id TEXT PRIMARY KEY, title TEXT NOT NULL, symbol TEXT NOT NULL, digest TEXT NOT NULL, pages TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE IF NOT EXISTS workspace_runs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE IF NOT EXISTS workspace_screens (name TEXT PRIMARY KEY, payload TEXT NOT NULL)",
        ):
            db.execute(statement)

    @staticmethod
    def name(value: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", value):
            raise ValueError("Name must contain 1-40 letters, numbers, underscores or dashes.")
        return value.lower()

    def save_layout(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        name = self.name(name)
        panels = payload.get("panels", LAYOUTS.get(name, LAYOUTS["research"]))
        if not isinstance(panels, list) or not 1 <= len(panels) <= 8 or any(p not in PANELS for p in panels):
            raise ValueError("Choose 1-8 supported panels.")
        symbols = payload.get("symbols", [])
        if not isinstance(symbols, list) or len(symbols) > 12:
            raise ValueError("At most 12 symbol tabs are supported.")
        from fincli.app.workspace.models import Instrument

        symbols = [Instrument.parse(str(s)).symbol for s in symbols]
        active = payload.get("symbol", symbols[0] if symbols else "")
        active = Instrument.parse(str(active)).symbol if active else ""
        if active and active not in symbols:
            symbols = ([*symbols, active])[-12:]
        interval = payload.get("interval", "1d")
        if interval not in {"1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}:
            raise ValueError("Unsupported interval.")
        data = {"name": name, "panels": panels, "symbols": symbols, "symbol": active, "interval": interval}
        self.db.execute(
            "INSERT INTO workspace_layouts(name,payload) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP",
            (name, json.dumps(data)),
        )
        return data

    def layouts(self) -> list[dict[str, Any]]:
        saved = {row["name"]: json.loads(row["payload"]) for row in self.db.query("SELECT * FROM workspace_layouts")}
        return [
            saved.pop(name, {"name": name, "panels": panels, "symbols": [], "symbol": "", "interval": "1d"})
            for name, panels in LAYOUTS.items()
        ] + list(saved.values())

    def save_run(self, run_id: str, kind: str, payload: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO workspace_runs(id,kind,payload) VALUES (?,?,?)",
            (run_id, kind, json.dumps(json_safe(payload), allow_nan=False)),
        )

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                "SELECT id,kind,created_at FROM workspace_runs ORDER BY rowid DESC LIMIT ?", (limit,)
            )
        ]

    def get_run(self, run_id: str) -> dict[str, Any]:
        rows = self.db.query("SELECT payload FROM workspace_runs WHERE id=?", (run_id,))
        if not rows:
            raise ValueError("Run not found.")
        return cast("dict[str, Any]", json.loads(rows[0]["payload"]))
