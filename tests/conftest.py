"""Shared pytest configuration for FinCLI tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    """Use a fresh in-memory credential backend; never touch developer keychains."""
    import os

    from keyring.backend import KeyringBackend

    from fincli.app.storage import secrets

    class MemoryKeyring(KeyringBackend):
        priority = 1

        def __init__(self):
            self.values = {}

        def get_password(self, service, username):
            return self.values.get((service, username))

        def set_password(self, service, username, password):
            self.values[service, username] = password

        def delete_password(self, service, username):
            self.values.pop((service, username), None)

    environment = dict(os.environ)
    backend = MemoryKeyring()
    monkeypatch.setattr(secrets._keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(secrets._keyring, "get_password", backend.get_password)
    monkeypatch.setattr(secrets._keyring, "set_password", backend.set_password)
    monkeypatch.setattr(secrets._keyring, "delete_password", backend.delete_password)
    yield
    os.environ.clear()
    os.environ.update(environment)


@pytest.fixture
def anyio_backend() -> str:
    """Textual's test runner is asyncio-based, so keep anyio tests on asyncio."""
    return "asyncio"
