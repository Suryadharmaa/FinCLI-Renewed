"""Autocomplete helpers for the command input."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fincli.app.cli.commands import CommandRegistry, CommandSpec


class SlashAutocomplete:
    """Return command suggestions while the user types."""

    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry

    def suggestions_for(self, text: str) -> list[CommandSpec]:
        if not text.startswith("/"):
            return []
        return self.registry.suggest(text, limit=50)
