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
            SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(e.id) AS event_count,
                   (SELECT e2.command FROM session_events e2 WHERE e2.session_id = s.id ORDER BY e2.id ASC LIMIT 1) AS first_command
            FROM sessions s
            LEFT JOIN session_events e ON e.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def get_session_summary(self, session_id: str, max_commands: int = 3) -> str:
        """Return first N commands as preview summary."""
        rows = self.db.query(
            "SELECT command FROM session_events WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, max_commands),
        )
        if not rows:
            return "(empty)"
        cmds = [str(row["command"])[:40] for row in rows]
        summary = " → ".join(cmds)
        if len(summary) > 100:
            summary = summary[:97] + "..."
        return summary

    def resume_session(self, session_id: str) -> dict[str, object] | None:
        """Return session + events for resuming context."""
        session = self.get_session(session_id)
        if not session:
            return None
        events = self.get_events(session_id)
        return {"session": session, "events": events}

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

    def cleanup_old_sessions(self, keep_days: int = 7, max_sessions: int = 50) -> int:
        """Clean up old sessions to prevent database bloat.

        Args:
            keep_days: Keep sessions newer than this many days
            max_sessions: Maximum number of sessions to keep (newest first)

        Returns:
            Number of sessions deleted.
        """
        # Count current sessions
        rows = self.db.query("SELECT COUNT(*) as cnt FROM sessions")
        current_count = int(rows[0]["cnt"]) if rows else 0

        if current_count <= max_sessions:
            return 0

        # Delete sessions older than keep_days
        self.db.execute(
            "DELETE FROM session_events WHERE session_id IN (SELECT id FROM sessions WHERE updated_at < datetime('now', ?))",
            (f"-{keep_days} days",),
        )
        self.db.execute(
            "DELETE FROM sessions WHERE updated_at < datetime('now', ?)",
            (f"-{keep_days} days",),
        )

        # If still too many, delete oldest sessions beyond max_sessions
        rows = self.db.query("SELECT COUNT(*) as cnt FROM sessions")
        remaining = int(rows[0]["cnt"]) if rows else 0

        if remaining > max_sessions:
            excess = remaining - max_sessions
            self.db.execute(
                """DELETE FROM session_events WHERE session_id IN (
                    SELECT id FROM sessions ORDER BY updated_at ASC LIMIT ?
                )""",
                (excess,),
            )
            self.db.execute(
                "DELETE FROM sessions WHERE id IN (SELECT id FROM sessions ORDER BY updated_at ASC LIMIT ?)",
                (excess,),
            )

        rows = self.db.query("SELECT COUNT(*) as cnt FROM sessions")
        final_count = int(rows[0]["cnt"]) if rows else 0
        return current_count - final_count

    def get_last_session(self, current_session_id: str) -> dict[str, object] | None:
        """Return most recent non-current session."""
        rows = self.db.query(
            """
            SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(e.id) AS event_count
            FROM sessions s
            LEFT JOIN session_events e ON e.session_id = s.id
            WHERE s.id != ?
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            LIMIT 1
            """,
            (current_session_id,),
        )
        return dict(rows[0]) if rows else None


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


def relative_time(iso_str: str) -> str:
    """Convert ISO timestamp to relative time string like '2m ago', '1h ago', 'yesterday'."""
    try:
        ts = datetime.fromisoformat(str(iso_str))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - ts
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            m = seconds // 60
            return f"{m}m ago"
        if seconds < 86400:
            h = seconds // 3600
            return f"{h}h ago"
        days = seconds // 86400
        if days == 1:
            return "yesterday"
        if days < 30:
            return f"{days}d ago"
        if days < 365:
            months = days // 30
            return f"{months}mo ago"
        years = days // 365
        return f"{years}y ago"
    except (ValueError, TypeError):
        return str(iso_str)
