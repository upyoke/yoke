"""What each harness can genuinely be asked for at launch."""

from __future__ import annotations

import pytest

from yoke_contracts.session_model_facts import CLAUDE_CONTEXT_TIER_TOKENS
from yoke_harness.model_request import (
    CLAUDE_EFFORT_ENV,
    CLAUDE_MAX_CONTEXT_ENV,
    requested_facts,
)


@pytest.fixture(autouse=True)
def _no_ambient_request(monkeypatch):
    """Start from a machine that has requested nothing."""
    for name in (
        "YOKE_MODEL",
        "CLAUDE_MODEL",
        "CODEX_MODEL",
        "DEFAULT_LLM_MODEL",
        CLAUDE_EFFORT_ENV,
        CLAUDE_MAX_CONTEXT_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_runtime._read_parent_argv", lambda: []
    )


def test_a_yoke_launch_stamps_the_model_it_asked_for(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MODEL", "claude-opus-5[1m]")

    facts = requested_facts("claude-code", {})

    assert facts.requested_model == "claude-opus-5[1m]"


def test_the_claude_tier_selector_is_recorded_as_a_window_request(
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MODEL", "claude-opus-5[1m]")

    facts = requested_facts("claude-code", {})

    assert facts.requested_context_window_tokens == CLAUDE_CONTEXT_TIER_TOKENS


def test_an_explicit_claude_cap_outranks_the_tier_selector(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MODEL", "claude-opus-5[1m]")
    monkeypatch.setenv(CLAUDE_MAX_CONTEXT_ENV, "400000")

    facts = requested_facts("claude-code", {})

    assert facts.requested_context_window_tokens == 400000


def test_claude_records_the_effort_its_own_env_channel_states(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MODEL", "claude-opus-5")
    monkeypatch.setenv(CLAUDE_EFFORT_ENV, "xhigh")

    facts = requested_facts("claude-code", {})

    assert facts.requested_reasoning_effort == "xhigh"


def test_cursor_reads_its_effort_out_of_the_variant_it_asked_for(
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MODEL", "cursor-grok-4.6-xhigh")

    facts = requested_facts("cursor", {})

    assert facts.requested_model == "cursor-grok-4.6-xhigh"
    assert facts.requested_reasoning_effort == "xhigh"


def test_codex_records_only_the_model_it_can_actually_be_asked_for(
    monkeypatch,
) -> None:
    """Effort and window are codex configuration, not a Yoke launch ask."""
    monkeypatch.setenv("CODEX_MODEL", "gpt-5.6-sol")

    facts = requested_facts("codex", {})

    assert facts.requested_model == "gpt-5.6-sol"
    assert facts.requested_reasoning_effort is None
    assert facts.requested_context_window_tokens is None


def test_a_wire_carried_request_is_preferred_over_local_detection(
    monkeypatch,
) -> None:
    """A relayed payload was resolved on the machine that was launched."""
    monkeypatch.setenv("YOKE_MODEL", "local-guess")

    facts = requested_facts("claude-code", {"requested_model": "claude-opus-5[1m]"})

    assert facts.requested_model == "claude-opus-5[1m]"


def test_a_machine_that_requested_nothing_records_nothing(monkeypatch) -> None:
    facts = requested_facts("claude-code", {})

    assert facts.requested_model is None


def test_a_placeholder_request_is_not_a_request(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_MODEL", "default")

    facts = requested_facts("claude-code", {})

    assert facts.requested_model is None
