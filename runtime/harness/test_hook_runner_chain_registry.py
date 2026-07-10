"""Tests for ``yoke_contracts.hook_runner.chain_registry``.

Covers the tool-shaped chains (PreToolUse Bash and apply_patch match the
universal ordering source) plus the harness-lifecycle slot the registry
surfaces inline so the runner can treat every event family uniformly.
"""

from __future__ import annotations

from yoke_contracts.hook_runner.chain_registry import chain_for
from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for


def test_chain_for_pretooluse_bash_matches_universal_ordering() -> None:
    """PreToolUse Bash chain is byte-equivalent to the universal source."""
    actual = chain_for("PreToolUse", "Bash")
    expected = list(ordered_pipeline_for("PreToolUse", "Bash"))
    assert actual == expected
    # Must also be a fresh list — caller mutation must not leak back.
    actual.append("yoke_core.domain.fake")
    assert chain_for("PreToolUse", "Bash") == expected


def test_chain_for_apply_patch_matches_universal_ordering() -> None:
    """apply_patch chain mirrors the universal ordering source."""
    actual = chain_for("apply_patch", None)
    # apply_patch is registered under PreToolUse[apply_patch] in the
    # universal table; the registry currently treats unknown event names
    # via direct lookup, so this assertion proves the public surface
    # delegates to the universal source.
    expected_pre = list(ordered_pipeline_for("PreToolUse", "apply_patch"))
    expected_event = list(ordered_pipeline_for("apply_patch", "_default"))
    # One of the two lookups must produce the chain (the universal source
    # registers it under PreToolUse). Whichever populates is the truth.
    assert actual in (expected_pre, expected_event), (
        f"apply_patch chain should derive from ordered_pipeline_for; got {actual}"
    )


def test_chain_for_lifecycle_events_returns_dispatch_entry() -> None:
    """Lifecycle events surface a non-empty dispatch list."""
    for event in (
        "SessionStart",
        "UserPromptSubmit",
        "SessionEnd",
        "Stop",
        "SubagentStop",
        "PreCompact",
        "Notification",
    ):
        chain = chain_for(event, None)
        assert isinstance(chain, list)
        assert chain, f"lifecycle event {event!r} produced empty chain"
        # Every entry must be a dotted Python module path string.
        for entry in chain:
            assert isinstance(entry, str) and "." in entry


def test_chain_for_unknown_event_returns_empty_list() -> None:
    """Unknown events produce an empty list (forward-compatible)."""
    assert chain_for("NotAnEvent", "Bash") == []


def test_chain_for_returns_fresh_copy_for_lifecycle_events() -> None:
    """Lifecycle list mutations must not leak back into the registry."""
    first = chain_for("SubagentStop", None)
    first.append("yoke_core.domain.fake")
    second = chain_for("SubagentStop", None)
    assert "yoke_core.domain.fake" not in second
