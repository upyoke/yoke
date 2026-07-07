"""Tests for yoke_core.domain.agents_render_conditional.

Covers the harness-conditional marker family used by the agent-render
pipeline to gate Claude-only prose out of Codex adapters (and vice-versa).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain.agents_render_conditional import (
    CLAUDE_HARNESS_ID,
    CODEX_HARNESS_ID,
    HARNESS_IDS,
    MarkerSyntaxError,
    apply_conditional_blocks,
    detect_conditional_marker_drift,
    find_conditional_pairs,
    validate_conditional_marker_syntax,
)


# ---------------------------------------------------------------------------
# Constant surface
# ---------------------------------------------------------------------------


def test_known_harness_ids_are_a_frozenset_with_claude_and_codex() -> None:
    """AC-1: harness ids come from one canonical Python constant."""
    assert isinstance(HARNESS_IDS, frozenset)
    assert CLAUDE_HARNESS_ID in HARNESS_IDS
    assert CODEX_HARNESS_ID in HARNESS_IDS


# ---------------------------------------------------------------------------
# find_conditional_pairs
# ---------------------------------------------------------------------------


def test_find_pairs_single_block() -> None:
    text = (
        "prose A\n"
        "<!-- YOKE:HARNESS claude start -->\n"
        "claude content\n"
        "<!-- YOKE:HARNESS end -->\n"
        "prose B\n"
    )
    pairs = find_conditional_pairs(text)
    assert len(pairs) == 1
    assert pairs[0]["harness"] == "claude"
    inner = text[pairs[0]["inner_start"] : pairs[0]["inner_end"]]
    assert inner == "claude content\n"


def test_find_pairs_multiple_blocks_independent_harnesses() -> None:
    text = (
        "<!-- YOKE:HARNESS claude start -->\nA\n<!-- YOKE:HARNESS end -->\n"
        "middle\n"
        "<!-- YOKE:HARNESS codex start -->\nB\n<!-- YOKE:HARNESS end -->\n"
    )
    pairs = find_conditional_pairs(text)
    assert [p["harness"] for p in pairs] == ["claude", "codex"]


def test_find_pairs_empty_when_no_markers() -> None:
    assert find_conditional_pairs("plain prose, no markers") == []


# ---------------------------------------------------------------------------
# Hard-error cases
# ---------------------------------------------------------------------------


def test_unmatched_start_marker_raises() -> None:
    text = "<!-- YOKE:HARNESS claude start -->\norphan\n"
    with pytest.raises(MarkerSyntaxError) as exc:
        find_conditional_pairs(text)
    assert "unmatched YOKE:HARNESS start" in str(exc.value)
    assert "line 1" in str(exc.value)


def test_unmatched_end_marker_raises() -> None:
    text = "stuff\n<!-- YOKE:HARNESS end -->\nmore\n"
    with pytest.raises(MarkerSyntaxError) as exc:
        find_conditional_pairs(text)
    assert "unmatched YOKE:HARNESS end" in str(exc.value)


def test_nested_block_raises() -> None:
    text = (
        "<!-- YOKE:HARNESS claude start -->\n"
        "<!-- YOKE:HARNESS codex start -->\n"
        "nested\n"
        "<!-- YOKE:HARNESS end -->\n"
        "<!-- YOKE:HARNESS end -->\n"
    )
    with pytest.raises(MarkerSyntaxError) as exc:
        find_conditional_pairs(text)
    assert "nested" in str(exc.value).lower()


def test_unknown_harness_id_raises() -> None:
    text = (
        "<!-- YOKE:HARNESS aider start -->\n"
        "body\n"
        "<!-- YOKE:HARNESS end -->\n"
    )
    with pytest.raises(MarkerSyntaxError) as exc:
        find_conditional_pairs(text)
    assert "unknown harness id" in str(exc.value)


# ---------------------------------------------------------------------------
# validate_conditional_marker_syntax
# ---------------------------------------------------------------------------


def test_validate_clean_text_returns_empty_list() -> None:
    text = (
        "<!-- YOKE:HARNESS claude start -->\nx\n<!-- YOKE:HARNESS end -->\n"
    )
    assert validate_conditional_marker_syntax(text) == []


def test_validate_text_with_no_markers_returns_empty_list() -> None:
    assert validate_conditional_marker_syntax("no markers here") == []


def test_validate_surfaces_unmatched_marker_as_issue_string() -> None:
    issues = validate_conditional_marker_syntax(
        "<!-- YOKE:HARNESS claude start -->\nbody\n"
    )
    assert len(issues) == 1
    assert "unmatched" in issues[0].lower()


# ---------------------------------------------------------------------------
# apply_conditional_blocks
# ---------------------------------------------------------------------------


def test_apply_keeps_matching_harness_strips_markers() -> None:
    text = (
        "prose A\n"
        "<!-- YOKE:HARNESS claude start -->\n"
        "CLAUDE_ONLY\n"
        "<!-- YOKE:HARNESS end -->\n"
        "prose B\n"
    )
    rendered = apply_conditional_blocks(text, "claude")
    assert rendered == "prose A\nCLAUDE_ONLY\nprose B\n"
    # Marker comments themselves are stripped.
    assert "YOKE:HARNESS" not in rendered


def test_apply_drops_non_matching_harness_block_entirely() -> None:
    text = (
        "prose A\n"
        "<!-- YOKE:HARNESS claude start -->\n"
        "CLAUDE_ONLY\n"
        "<!-- YOKE:HARNESS end -->\n"
        "prose B\n"
    )
    rendered = apply_conditional_blocks(text, "codex")
    assert rendered == "prose A\nprose B\n"
    assert "CLAUDE_ONLY" not in rendered
    assert "YOKE:HARNESS" not in rendered


def test_apply_handles_multiple_blocks_independently() -> None:
    text = (
        "<!-- YOKE:HARNESS claude start -->\nCLAUDE_BLOCK\n<!-- YOKE:HARNESS end -->\n"
        "middle\n"
        "<!-- YOKE:HARNESS codex start -->\nCODEX_BLOCK\n<!-- YOKE:HARNESS end -->\n"
    )
    claude_out = apply_conditional_blocks(text, "claude")
    assert "CLAUDE_BLOCK" in claude_out
    assert "CODEX_BLOCK" not in claude_out
    codex_out = apply_conditional_blocks(text, "codex")
    assert "CODEX_BLOCK" in codex_out
    assert "CLAUDE_BLOCK" not in codex_out


def test_apply_passes_through_text_without_markers() -> None:
    text = "no markers here\nat all\n"
    assert apply_conditional_blocks(text, "claude") == text
    assert apply_conditional_blocks(text, "codex") == text


def test_apply_inline_marker_collapses_cleanly() -> None:
    """Inline markers used in mid-sentence wrap a phrase, not a whole line."""
    text = (
        "Enforcement is tool-grant<!-- YOKE:HARNESS claude start -->"
        " plus PreToolUse hooks<!-- YOKE:HARNESS end -->.\n"
    )
    assert (
        apply_conditional_blocks(text, "claude")
        == "Enforcement is tool-grant plus PreToolUse hooks.\n"
    )
    assert (
        apply_conditional_blocks(text, "codex")
        == "Enforcement is tool-grant.\n"
    )


def test_apply_rejects_unknown_target_harness() -> None:
    with pytest.raises(ValueError) as exc:
        apply_conditional_blocks("no markers", "aider")
    assert "unknown target harness" in str(exc.value)


# ---------------------------------------------------------------------------
# Idempotency (AC-6 reuse of DB-packet marker contract)
# ---------------------------------------------------------------------------


def test_apply_is_idempotent_for_claude_render() -> None:
    text = (
        "head\n<!-- YOKE:HARNESS claude start -->\nC\n<!-- YOKE:HARNESS end -->\ntail\n"
    )
    once = apply_conditional_blocks(text, "claude")
    twice = apply_conditional_blocks(once, "claude")
    assert once == twice


def test_apply_is_idempotent_for_codex_render() -> None:
    text = (
        "head\n<!-- YOKE:HARNESS claude start -->\nC\n<!-- YOKE:HARNESS end -->\ntail\n"
    )
    once = apply_conditional_blocks(text, "codex")
    twice = apply_conditional_blocks(once, "codex")
    assert once == twice


# ---------------------------------------------------------------------------
# detect_conditional_marker_drift surface
# ---------------------------------------------------------------------------


def test_drift_helper_is_empty_when_markers_are_clean() -> None:
    text = (
        "<!-- YOKE:HARNESS claude start -->\nbody\n<!-- YOKE:HARNESS end -->\n"
    )
    assert detect_conditional_marker_drift(text, "fixture/agent.md") == []


def test_drift_helper_surfaces_label_and_issue() -> None:
    text = "<!-- YOKE:HARNESS claude start -->\norphan\n"
    drift = detect_conditional_marker_drift(text, "fixture/agent.md")
    assert len(drift) == 1
    assert drift[0].startswith("conditional-marker: fixture/agent.md:")
    assert "unmatched" in drift[0].lower()


# ---------------------------------------------------------------------------
# End-to-end render assertions
# ---------------------------------------------------------------------------


def test_render_pipeline_strips_claude_block_for_codex_variant(
    tmp_path: Path,
) -> None:
    """AC-7(b) + AC-11: a canonical body with a Claude-only block must
    render into a Claude variant containing the marker'd content and a
    Codex variant NOT containing it.
    """
    from yoke_core.domain.agents_render import (
        CANONICAL_DIR,
        render_claude_agent,
    )
    from yoke_core.domain.agents_render_codex import render_codex_agent_body

    canonical = tmp_path / CANONICAL_DIR
    canonical.mkdir(parents=True)
    body = (
        "shared prose\n\n"
        "<!-- YOKE:HARNESS claude start -->\n"
        "CLAUDE_ONLY_LINE\n"
        "<!-- YOKE:HARNESS end -->\n\n"
        "more shared prose\n"
    )
    (canonical / "engineer.md").write_text(body, encoding="utf-8")
    (canonical / "engineer.claude.json").write_text(
        '{"name": "yoke-engineer", "description": "x", '
        '"tools": "Read", "model": "opus"}',
        encoding="utf-8",
    )
    (canonical / "engineer.codex.json").write_text(
        '{"name": "yoke-engineer", "description": "x"}',
        encoding="utf-8",
    )

    claude_rendered = render_claude_agent("engineer", target_root=tmp_path)
    codex_body = render_codex_agent_body(canonical, "engineer")

    assert "CLAUDE_ONLY_LINE" in claude_rendered
    assert "YOKE:HARNESS" not in claude_rendered

    assert "CLAUDE_ONLY_LINE" not in codex_body
    assert "YOKE:HARNESS" not in codex_body
    # Shared prose must survive both renderings.
    assert "shared prose" in claude_rendered
    assert "shared prose" in codex_body


# ---------------------------------------------------------------------------
# Real-canonical regression: AC-4 + AC-10 + suggested 1668 body-prose AC
# ---------------------------------------------------------------------------


CLAUDE_ONLY_TOKENS = (
    "Monitor",
    "Bash(run_in_background",
    "ScheduleWakeup",
    "TaskOutput",
    "TaskStop",
    "PreToolUse",
)


@pytest.mark.parametrize("agent", ["engineer", "tester", "boss", "simulator"])
def test_real_codex_bodies_have_no_claude_only_tokens(agent: str) -> None:
    """The body that lands in the rendered Codex agent ``.toml`` must
    contain none of the Claude-only primitive references."""
    from yoke_core.domain.agents_render import CANONICAL_DIR
    from yoke_core.domain.agents_render_codex import render_codex_agent_body

    # Anchor the canonical directory to this test file's checkout root so
    # the assertion targets the same canonical body the test module was
    # loaded from (works under main checkout and under linked worktrees).
    checkout_root = Path(__file__).resolve().parents[3]
    canonical_dir = checkout_root / CANONICAL_DIR
    with patch("yoke_core.domain.schema_api_context._try_live_schema", return_value=None):
        body = render_codex_agent_body(canonical_dir, agent)
    for token in CLAUDE_ONLY_TOKENS:
        assert token not in body, (
            f"Codex render of {agent} still teaches Claude-only token "
            f"{token!r}; conditional markers must wrap the section"
        )
