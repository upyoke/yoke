"""Tests for yoke_core.domain.agents_render_field_note.

Covers the renderer contract: the single-line
``<!-- YOKE:FIELD-NOTE -->`` marker is recognized, expanded to
``field_note_text.FOOTER``, and every canonical agent body carries
exactly one marker at the documented insertion target. Rendered Claude /
Codex adapters carry the expanded text and no orphan markers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.agents_render import (
    CANONICAL_DIR,
    render_claude_agent,
)
from yoke_core.domain.agents_render_codex import render_codex_agent_body
from yoke_core.domain.agents_render_field_note import (
    MARKER,
    count_field_note_markers,
    detect_field_note_marker_drift,
    expand_field_note_markers,
)
from yoke_contracts.field_note_text import (
    BASIC_RECIPE,
    DIRECTIVE,
    FOOTER,
)
from runtime.api.domain.test_agents_render_workspace_fixtures import (
    resolve_live_repo_root,
)


# Canonical agent bodies that must carry the marker (7 Bash-capable
# subagents + 2 read-only sub-roles).
EXPECTED_MARKERED_AGENTS: tuple[str, ...] = (
    "architect",
    "boss",
    "engineer",
    "simulator",
    "tester",
    "tester-browser",
    "qa-walker",
    "product-manager",
    "product-designer",
)


@pytest.fixture
def repo_root() -> Path:
    return resolve_live_repo_root()


# ---------------------------------------------------------------------------
# Expansion behaviour
# ---------------------------------------------------------------------------


def test_marker_constant_matches_documented_spelling() -> None:
    assert MARKER == "<!-- YOKE:FIELD-NOTE -->"


def test_expand_no_marker_returns_input_unchanged() -> None:
    body = "## Heading\n\nSome content with no marker.\n"
    assert expand_field_note_markers(body) == body


def test_expand_replaces_single_marker_line_with_footer() -> None:
    body = f"intro line\n\n{MARKER}\n\n## Next heading\n"
    expanded = expand_field_note_markers(body)
    assert MARKER not in expanded
    assert FOOTER in expanded
    assert DIRECTIVE in expanded
    assert BASIC_RECIPE in expanded
    # Surrounding paragraph shape is preserved.
    assert expanded.startswith("intro line\n\n")
    assert expanded.endswith("## Next heading\n")


def test_expand_is_stable_on_already_expanded_text() -> None:
    body = f"intro\n\n{MARKER}\n\n## Next\n"
    once = expand_field_note_markers(body)
    twice = expand_field_note_markers(once)
    assert once == twice


def test_expand_handles_multiple_markers() -> None:
    # Defense — production canonical bodies carry one marker; expander
    # nonetheless expands every occurrence so a drifted body still
    # renders deterministically.
    body = f"{MARKER}\n\nbetween\n\n{MARKER}\n"
    expanded = expand_field_note_markers(body)
    assert MARKER not in expanded
    assert expanded.count(FOOTER) == 2


# ---------------------------------------------------------------------------
# Canonical body coverage
# ---------------------------------------------------------------------------


def test_every_expected_agent_body_carries_exactly_one_marker(
    repo_root: Path,
) -> None:
    for agent in EXPECTED_MARKERED_AGENTS:
        body = (repo_root / CANONICAL_DIR / f"{agent}.md").read_text(encoding="utf-8")
        count = count_field_note_markers(body)
        assert count == 1, (
            f"{agent}.md must carry exactly one YOKE:FIELD-NOTE marker; found {count}"
        )



def test_rendered_claude_adapter_carries_footer_and_no_marker(
    repo_root: Path,
) -> None:
    for agent in _RENDERED_AGENTS:
        rendered = render_claude_agent(agent, target_root=repo_root)
        assert MARKER not in rendered, (
            f"rendered Claude adapter for {agent} still carries the marker"
        )
        assert DIRECTIVE in rendered, (
            f"rendered Claude adapter for {agent} missing FOOTER directive"
        )
        assert BASIC_RECIPE in rendered, (
            f"rendered Claude adapter for {agent} missing FOOTER recipe line"
        )


def test_rendered_codex_adapter_body_carries_footer(repo_root: Path) -> None:
    canonical_dir = repo_root / CANONICAL_DIR
    for agent in _RENDERED_AGENTS:
        body = render_codex_agent_body(canonical_dir, agent)
        assert MARKER not in body, (
            f"rendered Codex body for {agent} still carries the marker"
        )
        assert FOOTER in body, f"rendered Codex body for {agent} missing FOOTER block"


def test_tester_browser_canonical_body_carries_marker_without_ouroboros(
    repo_root: Path,
) -> None:
    # tester-browser is served via symlink (no marker expansion at run
    # time), so the canonical body itself is what the agent reads. The
    # contract is the marker is present at the documented insertion
    # target — the absence of an Ouroboros section is why ``## Important
    # Notes`` is the anchor.
    body = (repo_root / CANONICAL_DIR / "tester-browser.md").read_text(encoding="utf-8")
    assert "## Ouroboros" not in body
    assert count_field_note_markers(body) == 1


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def test_drift_clean_body_returns_empty_list() -> None:
    body = f"intro\n\n{MARKER}\n\n## Next\n"
    assert detect_field_note_marker_drift(body, "x.md") == []


def test_drift_flags_multiple_markers() -> None:
    body = f"{MARKER}\n\n{MARKER}\n"
    drift = detect_field_note_marker_drift(body, "x.md")
    assert any("2 markers" in line for line in drift)


def test_drift_flags_hand_authored_directive_alongside_marker() -> None:
    body = f"{MARKER}\n\n{DIRECTIVE}\n"
    drift = detect_field_note_marker_drift(body, "x.md")
    assert any("hand-authored copy" in line for line in drift)


def test_drift_no_marker_no_flag_on_stale_text() -> None:
    # Without a marker we have no expansion contract — incidental matches
    # of canonical lines must not flag.
    body = DIRECTIVE + "\n"
    assert detect_field_note_marker_drift(body, "x.md") == []
