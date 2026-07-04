"""Tests for v1.2.0 plugin sandbox hardening."""

from __future__ import annotations

import pytest

from fincli.app.plugins.api import (
    FinCLIPluginAPI,
    PluginAPIError,
    PositionData,
    QuoteData,
    WatchlistData,
)
from fincli.app.plugins.loader import (
    ALLOWED_IMPORTS,
    BLOCKED_IMPORTS,
    is_plugin_code_safe,
    validate_plugin_code,
)

# --- Import Whitelist Tests ---


class TestImportWhitelist:
    def test_allowed_imports_contains_safe_modules(self):
        assert "json" in ALLOWED_IMPORTS
        assert "math" in ALLOWED_IMPORTS
        assert "datetime" in ALLOWED_IMPORTS
        assert "typing" in ALLOWED_IMPORTS

    def test_blocked_imports_contains_dangerous_modules(self):
        assert "os" in BLOCKED_IMPORTS
        assert "sys" in BLOCKED_IMPORTS
        assert "subprocess" in BLOCKED_IMPORTS
        assert "socket" in BLOCKED_IMPORTS
        assert "pathlib" in BLOCKED_IMPORTS

    def test_no_overlap(self):
        overlap = ALLOWED_IMPORTS & BLOCKED_IMPORTS
        assert len(overlap) == 0


# --- Plugin Code Validation Tests ---


class TestPluginCodeValidation:
    def test_safe_code_passes(self):
        code = """
import json
from datetime import datetime

def get_data():
    return {"price": 100}
"""
        violations = validate_plugin_code(code)
        assert len(violations) == 0

    def test_os_import_blocked(self):
        code = """
import os
os.listdir("/")
"""
        violations = validate_plugin_code(code)
        assert any(v.violation_type == "blocked_import" for v in violations)

    def test_sys_import_blocked(self):
        code = "import sys"
        violations = validate_plugin_code(code)
        assert any(v.violation_type == "blocked_import" for v in violations)

    def test_subprocess_import_blocked(self):
        code = "import subprocess"
        violations = validate_plugin_code(code)
        assert any(v.violation_type == "blocked_import" for v in violations)

    def test_from_import_blocked(self):
        code = "from os.path import join"
        violations = validate_plugin_code(code)
        assert any(v.violation_type == "blocked_import" for v in violations)

    def test_exec_call_blocked(self):
        code = "exec('print(1)')"
        violations = validate_plugin_code(code)
        assert any(v.violation_type == "dangerous_call" for v in violations)

    def test_eval_call_blocked(self):
        code = "eval('1+1')"
        violations = validate_plugin_code(code)
        assert any(v.violation_type == "dangerous_call" for v in violations)

    def test_open_call_blocked(self):
        code = 'f = open("/etc/passwd")'
        violations = validate_plugin_code(code)
        assert any(v.violation_type == "filesystem_access" for v in violations)

    def test_os_attribute_blocked(self):
        code = "os.listdir('/')"
        violations = validate_plugin_code(code)
        assert any(v.violation_type == "blocked_attribute" for v in violations)

    def test_syntax_error_reported(self):
        code = "def foo(:"  # Invalid syntax
        violations = validate_plugin_code(code)
        assert any(v.violation_type == "syntax_error" for v in violations)

    def test_fincli_import_allowed(self):
        code = "from fincli.plugins.api import FinCLIPluginAPI"
        violations = validate_plugin_code(code)
        assert len(violations) == 0

    def test_is_plugin_code_safe(self):
        safe_code = "import json\nx = json.dumps({'a': 1})"
        assert is_plugin_code_safe(safe_code) is True

        unsafe_code = "import os\nos.system('rm -rf /')"
        assert is_plugin_code_safe(unsafe_code) is False


# --- Plugin API Tests ---


class TestPluginAPI:
    def test_initial_state(self):
        api = FinCLIPluginAPI()
        assert api.get_logs() == []

    def test_log(self):
        api = FinCLIPluginAPI()
        api.log("Test message")
        assert "Test message" in api.get_logs()

    def test_clear_logs(self):
        api = FinCLIPluginAPI()
        api.log("Test")
        api.clear_logs()
        assert api.get_logs() == []

    def test_get_quote_no_provider(self):
        api = FinCLIPluginAPI()
        with pytest.raises(PluginAPIError, match="not available"):
            api.get_quote("AAPL")

    def test_get_portfolio_no_provider(self):
        api = FinCLIPluginAPI()
        with pytest.raises(PluginAPIError, match="not available"):
            api.get_portfolio()

    def test_get_watchlist_no_provider(self):
        api = FinCLIPluginAPI()
        with pytest.raises(PluginAPIError, match="not available"):
            api.get_watchlist()

    def test_add_alert_no_provider(self):
        api = FinCLIPluginAPI()
        with pytest.raises(PluginAPIError, match="not available"):
            api.add_alert("AAPL", "above", 200.0)

    def test_get_quote_with_provider(self):
        class MockQuote:
            symbol = "AAPL"
            price = 150.0
            currency = "USD"
            provider = "mock"
            status = "ok"

        api = FinCLIPluginAPI(quote_getter=lambda s: MockQuote())
        result = api.get_quote("AAPL")
        assert isinstance(result, QuoteData)
        assert result.symbol == "AAPL"
        assert result.price == 150.0

    def test_get_portfolio_with_provider(self):
        mock_data = [
            {"symbol": "AAPL", "quantity": 10, "average_price": 150.0, "currency": "USD"},
        ]
        api = FinCLIPluginAPI(portfolio_getter=lambda: mock_data)
        result = api.get_portfolio()
        assert len(result) == 1
        assert isinstance(result[0], PositionData)
        assert result[0].symbol == "AAPL"

    def test_get_watchlist_with_provider(self):
        mock_data = [
            {"symbol": "AAPL", "group": "tech", "notes": "breakout"},
        ]
        api = FinCLIPluginAPI(watchlist_getter=lambda g: mock_data)
        result = api.get_watchlist()
        assert len(result) == 1
        assert isinstance(result[0], WatchlistData)
        assert result[0].symbol == "AAPL"

    def test_add_alert_with_provider(self):
        alerts = []
        api = FinCLIPluginAPI(alert_adder=lambda s, c, v: alerts.append((s, c, v)))
        result = api.add_alert("AAPL", "above", 200.0)
        assert result is True
        assert len(alerts) == 1
