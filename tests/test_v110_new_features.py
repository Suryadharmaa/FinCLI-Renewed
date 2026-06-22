"""Tests for v1.1.0 new features: conversation context, portfolio rebalance, export broker."""

from __future__ import annotations

import pytest

from fincli.app.analysis.assistant_context import (
    ConversationHistory,
    build_fincli_assistant_prompt,
    get_conversation_history,
)


# --- Conversation History Tests ---


class TestConversationHistory:
    def test_initial_state(self):
        history = ConversationHistory()
        assert history.length == 0
        assert history.get_context() == ""

    def test_add_single_turn(self):
        history = ConversationHistory()
        history.add("What is AAPL price?", "AAPL is trading at $150")
        assert history.length == 1
        context = history.get_context()
        assert "What is AAPL price?" in context
        assert "AAPL is trading at $150" in context

    def test_add_multiple_turns(self):
        history = ConversationHistory()
        history.add("Question 1", "Answer 1")
        history.add("Question 2", "Answer 2")
        history.add("Question 3", "Answer 3")
        assert history.length == 3

    def test_max_turns_limit(self):
        history = ConversationHistory(max_tokens=4000, max_turns=2)
        history.add("Q1", "A1")
        history.add("Q2", "A2")
        history.add("Q3", "A3")
        assert history.length == 2
        context = history.get_context()
        assert "Q1" not in context
        assert "Q2" in context
        assert "Q3" in context

    def test_token_sliding_window(self):
        # Very small token budget forces eviction
        history = ConversationHistory(max_tokens=50, max_turns=10)
        history.add("Short", "OK")
        history.add("A" * 200, "B" * 200)  # ~100 tokens, exceeds budget
        # First turn should be evicted
        assert history.length == 1
        context = history.get_context()
        assert "Short" not in context

    def test_clear(self):
        history = ConversationHistory()
        history.add("Q1", "A1")
        history.clear()
        assert history.length == 0
        assert history.get_context() == ""

    def test_get_context_format(self):
        history = ConversationHistory()
        history.add("Test question", "Test answer")
        context = history.get_context()
        assert "Recent conversation:" in context
        assert "1. User: Test question" in context
        assert "Assistant: Test answer" in context

    def test_global_conversation_history(self):
        history = get_conversation_history()
        assert isinstance(history, ConversationHistory)
        # Clear to avoid affecting other tests
        history.clear()


# --- Prompt Builder with History Tests ---


class TestPromptBuilderWithHistory:
    def test_prompt_includes_history(self):
        history = ConversationHistory()
        history.add("What is RSI?", "RSI is a momentum indicator")
        prompt = build_fincli_assistant_prompt("Tell me more", conversation_history=history)
        assert "What is RSI?" in prompt
        assert "RSI is a momentum indicator" in prompt

    def test_prompt_without_history(self):
        prompt = build_fincli_assistant_prompt("Hello")
        assert "Recent conversation:" not in prompt

    def test_prompt_with_empty_history(self):
        history = ConversationHistory()
        prompt = build_fincli_assistant_prompt("Hello", conversation_history=history)
        assert "Recent conversation:" not in prompt

    def test_prompt_includes_instruction_about_context(self):
        prompt = build_fincli_assistant_prompt("Hello")
        assert "recent conversation context" in prompt.lower()


# --- Version Tests ---


class TestVersionBump:
    def test_version_is_1_3_0(self):
        from fincli import __version__
        assert __version__ == "1.5.1"

    def test_system_prompt_version(self):
        from fincli.app.analysis.assistant_context import FINCLI_ASSISTANT_SYSTEM_PROMPT
        assert "v1.5.1" in FINCLI_ASSISTANT_SYSTEM_PROMPT
