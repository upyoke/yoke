"""Tests for yoke_core.domain.agents_render_context — marker expansion.

Covers acceptance criteria AC-17 (marker syntax across all five canonical
agent prompts), AC-18 (Claude / Codex byte-identical packet bodies),
AC-19 (no hand-authored DB Quick Reference content alongside markers in
canonical agent prompts), and AC-21 (stale-term absence regression).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import schema_api_context
from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain.agents_render import (
    CANONICAL_DIR,
    detect_substrate_drift,
    render_claude_agent,
    write_all,
)
from yoke_core.domain.agents_render_codex import render_codex_agent_body
from yoke_core.domain.agents_render_context import (
    MARKER_END,
    MarkerSyntaxError,
    detect_packet_drift,
    expand_markers,
    find_marker_pairs,
    validate_marker_syntax,
)
from runtime.api.domain.test_agents_render_workspace_fixtures import (
    resolve_live_repo_root,
)


@pytest.fixture
def repo_root() -> Path:
    """Workspace-anchored live Yoke checkout root for renderer reads."""
    return resolve_live_repo_root()


def _make_marker(role: str, topic: str) -> str:
    return f"<!-- YOKE:DB-PACKET role={role} topic={topic} start -->"


# ---------------------------------------------------------------------------
# Marker discovery and validation
# ---------------------------------------------------------------------------


def test_find_marker_pairs_matches_role_and_topic() -> None:
    text = (
        "preamble\n"
        f"{_make_marker('engineer_agent', 'core')}\n\n"
        "old body\n\n"
        f"{MARKER_END}\n"
        "epilogue\n"
    )
    pairs = find_marker_pairs(text)
    assert len(pairs) == 1
    p = pairs[0]
    assert p["role"] == "engineer_agent"
    assert p["topic"] == "core"
    assert text[p["marker_start"] : p["marker_start_end"]] == _make_marker(
        "engineer_agent", "core"
    )
    assert text[p["marker_end_start"] : p["marker_end_end"]] == MARKER_END


def test_find_marker_pairs_handles_multiple_pairs() -> None:
    text = (
        f"{_make_marker('architect_agent', 'core')}\n\n{MARKER_END}\n"
        f"{_make_marker('architect_agent', 'claims')}\n\n{MARKER_END}\n"
    )
    pairs = find_marker_pairs(text)
    assert [(p["role"], p["topic"]) for p in pairs] == [
        ("architect_agent", "core"),
        ("architect_agent", "claims"),
    ]


def test_find_marker_pairs_unmatched_start_raises() -> None:
    text = f"{_make_marker('engineer_agent', 'core')}\nno end marker here\n"
    with pytest.raises(MarkerSyntaxError):
        find_marker_pairs(text)


def test_validate_marker_syntax_unknown_role_and_topic() -> None:
    text = f"{_make_marker('imposter', 'core')}\n{MARKER_END}\n"
    issues = validate_marker_syntax(text)
    assert any("imposter" in i for i in issues)
    text = f"{_make_marker('engineer_agent', 'unknown')}\n{MARKER_END}\n"
    issues = validate_marker_syntax(text)
    assert any("unknown" in i for i in issues)


def test_validate_marker_syntax_stray_end_marker() -> None:
    text = (
        f"{_make_marker('engineer_agent', 'core')}\n{MARKER_END}\n"
        f"stray:\n{MARKER_END}\n"
    )
    issues = validate_marker_syntax(text)
    assert any("without matching start" in i for i in issues)


def test_validate_marker_syntax_stray_end_before_start() -> None:
    text = f"{MARKER_END}\n{_make_marker('engineer_agent', 'core')}\n{MARKER_END}\n"
    issues = validate_marker_syntax(text)
    assert any("without matching start" in i for i in issues)


def test_validate_marker_syntax_stray_end_between_pairs() -> None:
    text = (
        f"{_make_marker('engineer_agent', 'core')}\n{MARKER_END}\n"
        f"{MARKER_END}\n"
        f"{_make_marker('engineer_agent', 'claims')}\n{MARKER_END}\n"
    )
    issues = validate_marker_syntax(text)
    assert any("without matching start" in i for i in issues)


def test_validate_marker_syntax_clean_returns_empty() -> None:
    text = f"{_make_marker('engineer_agent', 'core')}\n{MARKER_END}\n"
    assert validate_marker_syntax(text) == []


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


def test_expand_markers_replaces_body_with_packet() -> None:
    fresh = schema_api_context.render_topic_packet("core").rstrip("\n")
    text = (
        f"intro\n{_make_marker('engineer_agent', 'core')}\n"
        f"old body that should be replaced\n{MARKER_END}\noutro\n"
    )
    out = expand_markers(text)
    assert fresh in out
    assert "old body that should be replaced" not in out
    assert _make_marker("engineer_agent", "core") in out
    assert MARKER_END in out


def test_expand_markers_idempotent_on_fresh_text() -> None:
    body = schema_api_context.render_topic_packet("core").rstrip("\n")
    text = (
        f"{_make_marker('engineer_agent', 'core')}\n\n"
        f"{body}\n\n"
        f"{MARKER_END}\n"
    )
    once = expand_markers(text)
    twice = expand_markers(once)
    assert once == twice


def test_expand_markers_no_markers_is_passthrough() -> None:
    text = "plain canonical text with no markers\n"
    assert expand_markers(text) == text


def test_detect_packet_drift_clean_when_expanded() -> None:
    text = expand_markers(f"{_make_marker('tester_agent', 'qa')}\n{MARKER_END}\n")
    assert detect_packet_drift(text) == []


def test_detect_packet_drift_flags_stale_body() -> None:
    text = f"{_make_marker('tester_agent', 'qa')}\nSTALE_BODY\n{MARKER_END}\n"
    drift = detect_packet_drift(text)
    assert drift, f"expected drift entries for stale body, got {drift}"
    assert any("tester_agent" in d and "qa" in d for d in drift)


# ---------------------------------------------------------------------------
# Renderer integration
# ---------------------------------------------------------------------------


def test_render_claude_agent_expands_markers(tmp_path: Path) -> None:
    root = tmp_path
    canonical = root / CANONICAL_DIR
    canonical.mkdir(parents=True)
    (canonical / "architect.md").write_text(
        "Architect prompt body.\n\n"
        f"{_make_marker('architect_agent', 'core')}\n{MARKER_END}\n"
        "Tail content.\n",
        encoding="utf-8",
    )
    (canonical / "architect.claude.json").write_text(
        '{"name": "yoke-architect", "description": "x", "tools": "Read"}',
        encoding="utf-8",
    )
    rendered = render_claude_agent("architect", target_root=root)
    fresh_core = schema_api_context.render_topic_packet("core").rstrip("\n")
    assert fresh_core in rendered, "expander did not insert fresh core packet"
    assert _make_marker("architect_agent", "core") in rendered
    assert MARKER_END in rendered


def test_render_codex_body_expands_markers(tmp_path: Path) -> None:
    canonical = tmp_path
    body = (
        "Boss prompt body.\n\n"
        f"{_make_marker('boss_agent', 'claims')}\n{MARKER_END}\n"
    )
    (canonical / "boss.md").write_text(body, encoding="utf-8")
    (canonical / "boss.codex.json").write_text(
        '{"description": "x"}', encoding="utf-8"
    )
    rendered = render_codex_agent_body(canonical, "boss")
    fresh_claims = schema_api_context.render_topic_packet("claims").rstrip("\n")
    assert fresh_claims in rendered
    assert _make_marker("boss_agent", "claims") in rendered


def test_substrate_drift_flags_malformed_canonical_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path
    canonical = repo / CANONICAL_DIR
    canonical.mkdir(parents=True)
    (canonical / "architect.md").write_text(
        f"{_make_marker('architect_agent', 'core')}\nno end marker\n",
        encoding="utf-8",
    )
    (canonical / "architect.claude.json").write_text(
        '{"name": "yoke-architect", "description": "x", "tools": "Read"}',
        encoding="utf-8",
    )
    (canonical / "architect.codex.json").write_text(
        '{"name": "yoke-architect", "description": "x"}',
        encoding="utf-8",
    )
    monkeypatch.setattr("yoke_core.domain.agents_render.AGENTS", ["architect"])
    try:
        write_all(target_root=repo, dry_run=False)
    except MarkerSyntaxError:
        pass
    drift = detect_substrate_drift(target_root=repo)
    assert any("marker:" in d for d in drift), (
        f"expected marker drift entry for malformed canonical, got: {drift}"
    )


# ---------------------------------------------------------------------------
# Live canonical / rendered surface checks
# ---------------------------------------------------------------------------


_BASH_CAPABLE = ("architect", "engineer", "tester", "simulator", "boss")


def test_canonical_agent_prompts_have_no_stale_terms(repo_root: Path) -> None:
    """AC-21: canonical Bash-capable agent prompts must not contain stale schema names."""
    for role in _BASH_CAPABLE:
        path = repo_root / CANONICAL_DIR / f"{role}.md"
        text = path.read_text(encoding="utf-8")
        for stale in seed.STALE_TERMS:
            assert stale not in text, f"{role}.md contains stale term {stale!r}"


def test_rendered_claude_adapters_have_no_stale_terms(repo_root: Path) -> None:
    """AC-21: rendered Claude adapters must not contain stale schema names."""
    for role in _BASH_CAPABLE:
        rendered = render_claude_agent(role, target_root=repo_root)
        for stale in seed.STALE_TERMS:
            assert stale not in rendered, (
                f"rendered {role} adapter contains stale term {stale!r}"
            )


def test_canonical_agent_prompts_have_marker_pairs(repo_root: Path) -> None:
    """AC-17: each Bash-capable canonical prompt declares its expected marker pairs."""
    for role in _BASH_CAPABLE:
        text = (repo_root / CANONICAL_DIR / f"{role}.md").read_text(encoding="utf-8")
        pairs = find_marker_pairs(text)
        observed = {(p["role"], p["topic"]) for p in pairs}
        agent_role = f"{role}_agent"
        expected = {(agent_role, topic) for topic in seed.ROLE_TOPICS[agent_role]}
        assert observed == expected, (
            f"{role}.md marker pairs {observed} do not match expected {expected}"
        )


def test_canonical_marker_bodies_are_empty_or_fresh(repo_root: Path) -> None:
    """AC-19: hand-authored DB Quick Reference content must not coexist with markers.

    Canonical marker pair bodies are either empty (whitespace only) or
    byte-identical to the freshly generated packet. Anything else means a
    hand-edited copy is shadowing the generated content.
    """
    for role in _BASH_CAPABLE:
        text = (repo_root / CANONICAL_DIR / f"{role}.md").read_text(encoding="utf-8")
        for p in find_marker_pairs(text):
            body = text[p["marker_start_end"] : p["marker_end_start"]]
            stripped = body.strip()
            if not stripped:
                continue
            fresh = schema_api_context.render_topic_packet(p["topic"]).rstrip("\n")
            assert stripped == fresh.strip(), (
                f"{role}.md role={p['role']} topic={p['topic']}: marker body "
                f"contains hand-authored content; expected empty or fresh packet"
            )


def test_claude_and_codex_adapters_have_byte_identical_packet_bodies(
    repo_root: Path,
) -> None:
    """AC-18: same role + topic produces byte-identical body in Claude and Codex output."""
    canonical_dir = repo_root / CANONICAL_DIR
    for role in _BASH_CAPABLE:
        canonical_text = (canonical_dir / f"{role}.md").read_text(encoding="utf-8")
        pairs = find_marker_pairs(canonical_text)
        if not pairs:
            continue
        claude_rendered = render_claude_agent(role, target_root=repo_root)
        codex_rendered = render_codex_agent_body(canonical_dir, role)
        for p in pairs:
            fresh_body = schema_api_context.render_topic_packet(p["topic"]).rstrip("\n")
            assert fresh_body in claude_rendered, (
                f"role={role} topic={p['topic']}: missing in Claude render"
            )
            assert fresh_body in codex_rendered, (
                f"role={role} topic={p['topic']}: missing in Codex render"
            )
