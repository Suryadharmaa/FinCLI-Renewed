"""Stable command result shared by domain handlers and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CommandResult:
    renderable: Any
    status: str = "ready"
    clear: bool = False
    should_exit: bool = False
    metadata: dict[str, Any] | None = None
