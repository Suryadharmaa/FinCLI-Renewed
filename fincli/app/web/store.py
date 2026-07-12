"""Persistence for local web conversations and audit events."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fincli.app.storage.database import FinCLIDatabase


class WebStore:
    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def create_conversation(self, title: str, provider: str = "", model: str = "") -> dict[str, Any]:
        conversation_id = uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO web_conversations (id, title, provider, model) VALUES (?, ?, ?, ?)",
            (conversation_id, title[:120] or "New chat", provider, model),
        )
        return self.get_conversation(conversation_id) or {}

    def list_conversations(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM web_conversations WHERE archived = 0 ORDER BY pinned DESC, updated_at DESC"
        )
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        rows = self.db.query("SELECT * FROM web_conversations WHERE id = ?", (conversation_id,))
        if not rows:
            return None
        conversation = dict(rows[0])
        conversation["messages"] = [
            dict(row)
            for row in self.db.query(
                "SELECT * FROM web_messages WHERE conversation_id = ? ORDER BY created_at, rowid",
                (conversation_id,),
            )
        ]
        return conversation

    def delete_conversation(self, conversation_id: str) -> bool:
        self.db.execute("DELETE FROM web_messages WHERE conversation_id = ?", (conversation_id,))
        return self.db.execute("DELETE FROM web_conversations WHERE id = ?", (conversation_id,)) is not None

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        command: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO web_messages (id, conversation_id, role, content, command, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, conversation_id, role, content, command, json.dumps(metadata or {})),
        )
        self.db.execute(
            "UPDATE web_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (conversation_id,)
        )
        return {"id": message_id, "conversation_id": conversation_id, "role": role, "content": content, "command": command}

    def audit(self, action: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO web_audit_log (action, detail) VALUES (?, ?)", (action, detail[:500]))

    def logs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM web_audit_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),))
        return [dict(row) for row in rows]
