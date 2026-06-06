"""Trading journal service."""

from __future__ import annotations

from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.formatting import normalize_symbol


class JournalService:
    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def add(
        self,
        instrument: str,
        bias: str = "",
        entry_reason: str = "",
        exit_reason: str = "",
        result: str = "",
        emotion: str = "",
        lesson: str = "",
        tags: str = "",
    ) -> None:
        self.db.execute(
            """
            INSERT INTO journal_entries(
                instrument, bias, entry_reason, exit_reason, result, emotion, lesson, tags
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalize_symbol(instrument),
                bias,
                entry_reason,
                exit_reason,
                result,
                emotion,
                lesson,
                tags,
            ),
        )

    def list(self, instrument: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        if instrument:
            rows = self.db.query(
                """
                SELECT id, instrument, bias, entry_reason, result, emotion, lesson, tags, created_at
                FROM journal_entries
                WHERE instrument = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (normalize_symbol(instrument), limit),
            )
        else:
            rows = self.db.query(
                """
                SELECT id, instrument, bias, entry_reason, result, emotion, lesson, tags, created_at
                FROM journal_entries
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [dict(row) for row in rows]
