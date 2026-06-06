"""Lightweight in-memory TTL cache for provider responses."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class CacheEntry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    """Simple runtime TTL cache used by router and provider workflows."""

    def __init__(self, default_ttl: int = 300) -> None:
        self.default_ttl = default_ttl
        self._items: dict[str, CacheEntry[T]] = {}

    def get(self, key: str) -> T | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at < monotonic():
            self._items.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: T, ttl: int | None = None) -> None:
        self._items[key] = CacheEntry(value=value, expires_at=monotonic() + (ttl or self.default_ttl))

    def clear(self) -> None:
        self._items.clear()
