"""Session history service for FinCLI commands."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from uuid import uuid4

from fincli.app.storage.database import FinCLIDatabase


_AI_NEWS_KEY_PATTERN = re.compile(r"^/(ai_model|news_model)\s+key\s+(\S+)\s+(.+)$", re.IGNORECASE)
_PROVIDER_KEY_PATTERN = re.compile(r"^/provider\s+key\s+(\S+)\s+(.+)$", re.IGNORECASE)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)(api[_ -]?key|token|secret|password)\s*[:=]\s*\S+"),
)


class SessionHistoryService:
    """Persist local command sessions and sanitized command events."""

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def start_session(self, title: str = "FinCLI session") -> str:
        session_id = uuid4().hex[:12]
        now = _now()
        self.db.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title, now, now),
        )
        return session_id

    def save_session(self, session_id: str, title: str) -> None:
        self.db.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title.strip() or "FinCLI session", _now(), session_id),
        )

    def record_event(self, session_id: str, command: str, status: str, output_preview: str = "") -> None:
        sanitized_command = sanitize_history_text(command.strip())
        sanitized_output = sanitize_history_text(output_preview.strip())[:1200]
        if not sanitized_command:
            return
        self.db.execute(
            """
            INSERT INTO session_events (session_id, command, status, output_preview, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, sanitized_command, status, sanitized_output, _now()),
        )
        self.db.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (_now(), session_id))

    def list_sessions(self, limit: int = 20) -> list[dict[str, object]]:
        rows = self.db.query(
            """
            SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(e.id) AS event_count
            FROM sessions s
            LEFT JOIN session_events e ON e.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def get_events(self, session_id: str, limit: int = 100) -> list[dict[str, object]]:
        rows = self.db.query(
            """
            SELECT id, command, status, output_preview, created_at
            FROM session_events
            WHERE session_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (session_id, limit),
        )
        return [dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict[str, object] | None:
        rows = self.db.query("SELECT id, title, created_at, updated_at FROM sessions WHERE id = ?", (session_id,))
        return dict(rows[0]) if rows else None

    def delete_session(self, session_id: str) -> int:
        self.db.execute("DELETE FROM session_events WHERE session_id = ?", (session_id,))
        self.db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return 1

    def clear_events(self, session_id: str) -> None:
        self.db.execute("DELETE FROM session_events WHERE session_id = ?", (session_id,))
        self.db.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (_now(), session_id))

    def clear_all(self) -> None:
        self.db.execute("DELETE FROM session_events")
        self.db.execute("DELETE FROM sessions")


def sanitize_history_text(value: str) -> str:
    sanitized = value
    match = _AI_NEWS_KEY_PATTERN.match(sanitized)
    if match:
        return f"/{match.group(1)} key {match.group(2)} <redacted>"
    match = _PROVIDER_KEY_PATTERN.match(sanitized)
    if match:
        return f"/provider key {match.group(1)} <redacted>"
    for pattern in _SECRET_VALUE_PATTERNS:
        sanitized = pattern.sub(lambda match: f"{match.group(1)}=<redacted>", sanitized)
    return sanitized


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
