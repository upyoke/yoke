"""Tests for ``yoke_core.domain.agents_render_hooks``.

Every Claude hook entry routes through one ``yoke hook evaluate <event>``
command, and a matcherless entry matches every tool — so events whose
chain applies via ``_default`` must render exactly one matcherless entry
rather than fanning the same command out across per-tool matchers.
"""

from __future__ import annotations

from yoke_core.domain.agents_render_hooks import render_claude_hooks_block


def test_default_only_events_render_single_matcherless_entry() -> None:
    block = render_claude_hooks_block()
    for event in ("SessionStart", "SessionEnd", "Stop", "UserPromptSubmit"):
        entries = block[event]
        assert len(entries) == 1, (event, entries)
        assert "matcher" not in entries[0], (event, entries)


def test_posttool_events_have_no_redundant_per_tool_fanout() -> None:
    """The matcherless ``_default`` entry covers every tool; explicit
    matcher entries exist only for tools with their own registered chain."""
    block = render_claude_hooks_block()

    post = block["PostToolUse"]
    matcherless = [e for e in post if "matcher" not in e]
    assert len(matcherless) == 1, post
    assert {e["matcher"] for e in post if "matcher" in e} == {"Bash", "Agent"}

    post_failure = block["PostToolUseFailure"]
    assert len(post_failure) == 1, post_failure
    assert "matcher" not in post_failure[0], post_failure


def test_entries_are_unique_per_event() -> None:
    block = render_claude_hooks_block()
    for event, entries in block.items():
        matchers = [e.get("matcher") for e in entries]
        assert len(matchers) == len(set(matchers)), (event, matchers)
