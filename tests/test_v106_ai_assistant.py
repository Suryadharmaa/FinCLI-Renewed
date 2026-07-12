"""Tests for v1.0.6 AI assistant features: command-aware context, feature reference, /assistant command."""

from __future__ import annotations

from fincli.app.analysis.assistant_context import (
    FINCLI_ASSISTANT_SYSTEM_PROMPT,
    build_command_reference,
    build_fincli_assistant_prompt,
    build_fincli_feature_context,
)
from fincli.app.cli.commands import COMMANDS, CommandRegistry

# --- System prompt tests ---


class TestSystemPrompt:
    def test_version_is_1_0_5(self):
        assert "v1.9.0" in FINCLI_ASSISTANT_SYSTEM_PROMPT

    def test_contains_command_reference_instruction(self):
        assert "Command Reference" in FINCLI_ASSISTANT_SYSTEM_PROMPT

    def test_contains_coding_boundary(self):
        assert "Coding boundary" in FINCLI_ASSISTANT_SYSTEM_PROMPT

    def test_contains_financial_rules(self):
        assert "Financial analysis rules" in FINCLI_ASSISTANT_SYSTEM_PROMPT


# --- Command reference builder tests ---


class TestBuildCommandReference:
    def test_returns_non_empty(self):
        ref = build_command_reference()
        assert len(ref) > 0

    def test_contains_all_commands(self):
        ref = build_command_reference()
        for cmd in COMMANDS:
            assert cmd.name in ref, f"Command {cmd.name} not in reference"

    def test_contains_group_headers(self):
        ref = build_command_reference()
        assert "[AI]" in ref
        assert "[Market]" in ref
        assert "[Portfolio]" in ref
        assert "[System]" in ref

    def test_contains_descriptions(self):
        ref = build_command_reference()
        assert "Research Engine v3" in ref or "/research" in ref

    def test_contains_examples(self):
        ref = build_command_reference()
        assert "Example:" in ref


# --- Feature context tests ---


class TestBuildFincliFeatureContext:
    def test_returns_non_empty(self):
        ctx = build_fincli_feature_context()
        assert len(ctx) > 0

    def test_contains_version(self):
        from fincli import __version__
        ctx = build_fincli_feature_context()
        assert f"v{__version__}" in ctx

    def test_contains_key_features(self):
        ctx = build_fincli_feature_context()
        assert "Research Engine v3" in ctx
        assert "Portfolio Risk v3" in ctx
        assert "Provider System v2" in ctx
        assert "Trading Safety Layer" in ctx
        assert "Backtesting" in ctx
        assert "Watchlist" in ctx
        assert "Journal" in ctx
        assert "Alert" in ctx
        assert "Theme" in ctx
        assert "Plugin" in ctx
        assert "Security" in ctx

    def test_contains_commands(self):
        ctx = build_fincli_feature_context()
        assert "/research" in ctx
        assert "/trading" in ctx
        assert "/scan" in ctx
        assert "/backtest" in ctx


# --- Prompt builder tests ---


class TestBuildFincliAssistantPrompt:
    def test_includes_system_prompt(self):
        from fincli import __version__
        prompt = build_fincli_assistant_prompt("test")
        assert "FinCLI AI Assistance" in prompt
        assert f"v{__version__}" in prompt

    def test_includes_command_reference(self):
        prompt = build_fincli_assistant_prompt("test")
        assert "Command Reference" in prompt
        assert "/research" in prompt

    def test_includes_feature_context(self):
        prompt = build_fincli_assistant_prompt("test")
        assert "Research Engine v3" in prompt
        assert "Portfolio Risk v3" in prompt

    def test_includes_user_prompt(self):
        prompt = build_fincli_assistant_prompt("cara pakai /research")
        assert "cara pakai /research" in prompt

    def test_includes_market_context(self):
        prompt = build_fincli_assistant_prompt("test", market_context="AAPL: $150")
        assert "AAPL: $150" in prompt

    def test_default_market_context(self):
        prompt = build_fincli_assistant_prompt("test")
        assert "No explicit market context" in prompt

    def test_includes_instruction_about_commands(self):
        prompt = build_fincli_assistant_prompt("test")
        assert "reference specific commands" in prompt


# --- Command registration tests ---


class TestAICommandRegistered:
    def test_ai_in_commands(self):
        names = [cmd.name for cmd in COMMANDS]
        assert "/ai" in names

    def test_ai_group_is_ai(self):
        for cmd in COMMANDS:
            if cmd.name == "/ai":
                assert cmd.group == "AI"
                break

    def test_registry_suggests_ai(self):
        registry = CommandRegistry()
        suggestions = registry.suggest("/ai")
        names = [s.name for s in suggestions]
        assert "/ai" in names
