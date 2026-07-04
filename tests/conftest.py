"""Shared pytest configuration for FinCLI tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Textual's test runner is asyncio-based, so keep anyio tests on asyncio."""
    return "asyncio"
