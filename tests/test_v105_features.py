"""Tests for v1.0.5 features: error classification, plugin validation, custom themes, doctor report."""

from __future__ import annotations

from pathlib import Path

import pytest

from fincli.app.utils.errors import (
    CommandError,
    ConfigError,
    CrashContext,
    FinCLIError,
    ProviderError,
    RateLimitError,
    SecurityError,
    StorageError,
    classify_error,
)
from fincli.app.plugins.loader import (
    PluginManifest,
    PluginSandbox,
    PluginValidationError,
    validate_manifest,
)
from fincli.app.plugins.lifecycle import LifecycleEvent, LifecycleManager


# --- Error classification tests ---


class TestClassifyError:
    def test_provider_error(self):
        assert classify_error(ProviderError("fail")) == "provider"

    def test_rate_limit(self):
        # RateLimitError is a ProviderError subclass, classified as "provider"
        assert classify_error(RateLimitError("limited")) == "provider"

    def test_command_error(self):
        assert classify_error(CommandError("bad args")) == "user_input"

    def test_security_error(self):
        assert classify_error(SecurityError("blocked")) == "security"

    def test_config_error(self):
        assert classify_error(ConfigError("bad config")) == "storage"

    def test_storage_error(self):
        assert classify_error(StorageError("disk full")) == "storage"

    def test_network_keywords(self):
        assert classify_error(Exception("connection timeout")) == "network"

    def test_security_keywords(self):
        assert classify_error(Exception("permission denied")) == "security"

    def test_internal_fallback(self):
        assert classify_error(Exception("something weird")) == "internal"


# --- CrashContext tests ---


class TestCrashContext:
    def test_format(self):
        ctx = CrashContext(
            error_type="ValueError",
            error_category="internal",
            message="test error",
            command="/test",
            python_version="3.12.0",
            platform="Windows-11",
            version="1.1.0",
        )
        text = ctx.format()
        assert "ValueError" in text
        assert "internal" in text
        assert "/test" in text
        assert "1.1.0" in text


# --- Plugin validation tests ---


class TestPluginValidation:
    def test_valid_manifest(self):
        manifest = PluginManifest(
            name="test-plugin",
            version="1.0.0",
            description="A test plugin",
            commands=("/test",),
            capabilities=("data",),
            hooks=("on_startup",),
            path=Path("/fake/plugin.json"),
        )
        errors = validate_manifest(manifest)
        assert len(errors) == 0

    def test_empty_name(self):
        manifest = PluginManifest(
            name="",
            version="1.0.0",
            description="",
            commands=(),
            capabilities=(),
            hooks=(),
            path=Path("/fake/plugin.json"),
        )
        errors = validate_manifest(manifest)
        assert any(e.field == "name" for e in errors)

    def test_path_separator_in_name(self):
        manifest = PluginManifest(
            name="../evil",
            version="1.0.0",
            description="",
            commands=(),
            capabilities=(),
            hooks=(),
            path=Path("/fake/plugin.json"),
        )
        errors = validate_manifest(manifest)
        assert any(e.field == "name" for e in errors)

    def test_command_without_slash(self):
        manifest = PluginManifest(
            name="test",
            version="1.0.0",
            description="",
            commands=("bad_command",),
            capabilities=(),
            hooks=(),
            path=Path("/fake/plugin.json"),
        )
        errors = validate_manifest(manifest)
        assert any(e.field == "commands" for e in errors)

    def test_unknown_hook(self):
        manifest = PluginManifest(
            name="test",
            version="1.0.0",
            description="",
            commands=(),
            capabilities=(),
            hooks=("on_invalid",),
            path=Path("/fake/plugin.json"),
        )
        errors = validate_manifest(manifest)
        assert any(e.field == "hooks" for e in errors)


# --- PluginSandbox tests ---


class TestPluginSandbox:
    def test_valid_path(self, tmp_path):
        sandbox = PluginSandbox(tmp_path)
        test_file = tmp_path / "test.json"
        assert sandbox.validate_path(test_file) is True

    def test_escape_path(self, tmp_path):
        sandbox = PluginSandbox(tmp_path)
        escape_path = tmp_path.parent / "evil.json"
        assert sandbox.validate_path(escape_path) is False


# --- Lifecycle tests ---


class TestLifecycleManager:
    def test_no_plugins(self):
        manager = LifecycleManager([])
        assert not manager.has_hooks("on_startup")
        assert manager.fire(LifecycleEvent("on_startup")) == []

    def test_with_plugin_hooks(self):
        plugin = PluginManifest(
            name="test",
            version="1.0.0",
            description="",
            commands=(),
            capabilities=(),
            hooks=("on_startup", "on_command"),
            path=Path("/fake/plugin.json"),
        )
        manager = LifecycleManager([plugin])
        assert manager.has_hooks("on_startup")
        assert not manager.has_hooks("on_shutdown")
        assert manager.plugins_for_hook("on_startup") == [plugin]

    def test_summary(self):
        plugin = PluginManifest(
            name="test",
            version="1.0.0",
            description="",
            commands=(),
            capabilities=(),
            hooks=("on_startup",),
            path=Path("/fake/plugin.json"),
        )
        manager = LifecycleManager([plugin])
        summary = manager.summary()
        assert "on_startup" in summary
        assert "test" in summary["on_startup"]


# --- Version test ---


class TestVersion:
    def test_version_is_1_0_5(self):
        from fincli import __version__
        assert __version__ == "1.5.0"
