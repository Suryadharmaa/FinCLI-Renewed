"""Session state auto-save and recovery for FinCLI v1.2.0.

Periodically saves UI state (command buffer, output history, layout)
to enable instant resume after crash.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fincli.app.storage.database import FinCLIDatabase


@dataclass
class SessionState:
    """Captured UI state for recovery."""
    session_id: str
    command_buffer: str = ""
    output_entries: list[dict[str, str]] = field(default_factory=list)
    active_command: str = ""
    status_bar: str = ""
    timestamp: float = 0.0
    is_dirty: bool = False
    version: str = "1.2.0"


class SessionStateManager:
    """Manages auto-save and recovery of session state.

    Saves state periodically to SQLite for crash recovery.
    """

    SAVE_INTERVAL_SECONDS = 60
    MAX_OUTPUT_ENTRIES = 100

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db
        self._last_save_time: float = 0.0
        self._current_state: SessionState | None = None
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create session_state table if not exists."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS session_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_clean_shutdown INTEGER DEFAULT 0
            )
        """)

    def init_session(self, session_id: str) -> None:
        """Initialize a new session state."""
        self._current_state = SessionState(
            session_id=session_id,
            timestamp=time.time(),
        )
        self._last_save_time = time.time()

    def update_buffer(self, buffer: str) -> None:
        """Update command buffer."""
        if self._current_state:
            self._current_state.command_buffer = buffer
            self._current_state.is_dirty = True

    def add_output(self, text: str, command: str = "") -> None:
        """Add an output entry."""
        if self._current_state:
            entry = {
                "text": text[:500],  # Truncate long outputs
                "command": command,
                "time": datetime.now(timezone.utc).isoformat(),
            }
            self._current_state.output_entries.append(entry)
            # Keep only last N entries
            if len(self._current_state.output_entries) > self.MAX_OUTPUT_ENTRIES:
                self._current_state.output_entries = self._current_state.output_entries[-self.MAX_OUTPUT_ENTRIES:]
            self._current_state.is_dirty = True

    def update_status(self, status: str) -> None:
        """Update status bar text."""
        if self._current_state:
            self._current_state.status_bar = status
            self._current_state.is_dirty = True

    def update_active_command(self, command: str) -> None:
        """Update currently executing command."""
        if self._current_state:
            self._current_state.active_command = command
            self._current_state.is_dirty = True

    def should_save(self) -> bool:
        """Check if enough time has passed to auto-save."""
        if not self._current_state or not self._current_state.is_dirty:
            return False
        return (time.time() - self._last_save_time) >= self.SAVE_INTERVAL_SECONDS

    def save(self, force: bool = False) -> bool:
        """Save current state to database.

        Returns True if state was saved.
        """
        if not self._current_state:
            return False

        if not force and not self._current_state.is_dirty:
            return False

        state_dict = asdict(self._current_state)
        state_json = json.dumps(state_dict, ensure_ascii=False)

        self.db.execute(
            "INSERT INTO session_state (session_id, state_json, is_clean_shutdown) VALUES (?, ?, 0)",
            (self._current_state.session_id, state_json),
        )

        self._current_state.is_dirty = False
        self._last_save_time = time.time()
        return True

    def mark_clean_shutdown(self) -> None:
        """Mark all snapshots for current session as cleanly shut down."""
        if self._current_state:
            self.db.execute(
                "UPDATE session_state SET is_clean_shutdown = 1 WHERE session_id = ?",
                (self._current_state.session_id,),
            )

    def get_last_unclean_state(self) -> SessionState | None:
        """Get the last unclean session state for recovery.

        Returns None if no recovery needed.
        """
        rows = self.db.query(
            """SELECT state_json FROM session_state
               WHERE is_clean_shutdown = 0
               ORDER BY id DESC LIMIT 1"""
        )
        if not rows:
            return None

        try:
            state_dict = json.loads(rows[0]["state_json"])
            return SessionState(**state_dict)
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

    def get_recovery_summary(self, state: SessionState) -> str:
        """Generate a human-readable summary of recoverable state."""
        lines = [
            f"Session ID: {state.session_id}",
            f"Last saved: {datetime.fromtimestamp(state.timestamp, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        ]
        if state.command_buffer:
            lines.append(f"Command buffer: {state.command_buffer}")
        if state.output_entries:
            lines.append(f"Output entries: {len(state.output_entries)} saved")
        if state.active_command:
            lines.append(f"Last command: {state.active_command}")
        return "\n".join(lines)

    def restore_state(self, state: SessionState) -> dict[str, Any]:
        """Restore state from a saved session.

        Returns dict with restored components.
        """
        return {
            "session_id": state.session_id,
            "command_buffer": state.command_buffer,
            "output_entries": state.output_entries,
            "status_bar": state.status_bar,
        }

    def clear_old_states(self, keep_days: int = 7) -> int:
        """Clear session states older than keep_days.

        Returns number of rows deleted.
        """
        rows = self.db.query(
            "SELECT COUNT(*) as cnt FROM session_state WHERE created_at < datetime('now', ?)",
            (f"-{keep_days} days",),
        )
        count = int(rows[0]["cnt"]) if rows else 0

        self.db.execute(
            "DELETE FROM session_state WHERE created_at < datetime('now', ?)",
            (f"-{keep_days} days",),
        )
        return count

    @property
    def current_state(self) -> SessionState | None:
        return self._current_state
