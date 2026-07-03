"""Security audit logging for FinCLI (v1.0.0).

Immutable audit trail for security-relevant events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fincli.app.storage.database import FinCLIDatabase

# ---------------------------------------------------------------------------
# Audit event model
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: int
    event_type: str
    detail: str
    ip_address: str
    created_at: str


# Event types
EVENT_SECRET_ACCESS = "secret_access"
EVENT_SECRET_SAVE = "secret_save"
EVENT_SECRET_CLEAR = "secret_clear"
EVENT_CONFIG_CHANGE = "config_change"
EVENT_EXPORT_DATA = "export_data"
EVENT_PRIVACY_PURGE = "privacy_purge"
EVENT_LOGIN = "login"
EVENT_LOGOUT = "logout"
EVENT_RATE_LIMIT = "rate_limit"
EVENT_SECURITY_VIOLATION = "security_violation"
EVENT_PATH_TRAVERSAL = "path_traversal"
EVENT_INPUT_VALIDATION = "input_validation"


class SecurityAuditLog:
    """Immutable audit log for security events."""

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create audit table if it doesn't exist."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS security_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                ip_address TEXT DEFAULT 'local',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def record(self, event_type: str, detail: str = "", ip_address: str = "local") -> None:
        """Record a security event (immutable)."""
        self.db.execute(
            "INSERT INTO security_audit (event_type, detail, ip_address) VALUES (?, ?, ?)",
            (event_type, detail, ip_address),
        )

    def list_events(self, limit: int = 50, event_type: str | None = None) -> list[AuditEvent]:
        """List recent audit events."""
        if event_type:
            rows = self.db.query(
                "SELECT id, event_type, detail, ip_address, created_at "
                "FROM security_audit WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                (event_type, limit),
            )
        else:
            rows = self.db.query(
                "SELECT id, event_type, detail, ip_address, created_at "
                "FROM security_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return [
            AuditEvent(
                id=int(row["id"]),
                event_type=str(row["event_type"]),
                detail=str(row["detail"]),
                ip_address=str(row["ip_address"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def count_events(self, event_type: str | None = None) -> int:
        """Count audit events."""
        if event_type:
            rows = self.db.query(
                "SELECT COUNT(*) as count FROM security_audit WHERE event_type = ?",
                (event_type,),
            )
        else:
            rows = self.db.query("SELECT COUNT(*) as count FROM security_audit")
        return int(rows[0]["count"]) if rows else 0

    def clear_old_events(self, days: int = 90) -> int:
        """Clear audit events older than N days."""
        rows = self.db.query(
            "SELECT COUNT(*) as count FROM security_audit WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        count = int(rows[0]["count"]) if rows else 0
        if count > 0:
            self.db.execute(
                "DELETE FROM security_audit WHERE created_at < datetime('now', ?)",
                (f"-{days} days",),
            )
        return count
