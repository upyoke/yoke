"""Tests for yoke_core.domain.agents_render — canonical agent layer renderer.

Agent-render layer tests (Claude .md adapter tree + drift surface).
Universal-substrate (Codex .toml tree, both manifests, hook configs)
coverage lives in `test_agents_render_substrate.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.agents_render import (
    AGENTS,
    CANONICAL_DIR,
    CLAUDE_OUT_DIR,
    CLAUDE_SPEC_KEY_ORDER,
    detect_drift,
    load_canonical,
    load_claude_spec,
    render_claude_agent,
    write_all_claude,
)
from runtime.api.domain.test_agents_render_workspace_fixtures import (
    resolve_live_repo_root,
)

# AC-1 / AC-2 / AC-5 reader-anchor regressions live in the sibling module
# ``test_agents_render_workspace_anchor.py`` so this file stays under the
# 350-line authoring cap.


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_root() -> Path:
    """Return the workspace-anchored live Yoke checkout root.

    Resolves via ``$YOKE_BOUND_WORKSPACE`` or a ``Path(__file__)``
    walk-up — never via the process cwd, so byte-identity tests produce
    identical outcomes from main, from a linked worktree, or from /tmp.
    """
    return resolve_live_repo_root()


@pytest.fixture
def temp_agent_env(tmp_path: Path) -> Path:
    """Create a minimal canonical + output tree in a temp directory.

    Returns the temp dir that acts as the repo root.
    """
    canonical = tmp_path / CANONICAL_DIR
    canonical.mkdir(parents=True)
    out = tmp_path / CLAUDE_OUT_DIR
    out.mkdir(parents=True)

    # Write a minimal agent
    (canonical / "architect.md").write_text("You are an architect.\n")
    (canonical / "architect.claude.json").write_text(
        '{"name": "yoke-architect", "description": "Plans things", '
        '"tools": "Read, Grep", "model": "opus", "maxTurns": 20}'
    )

    return tmp_path


def test_render_format(repo_root: Path) -> None:
    """Output starts with ---\\n, contains frontmatter block, body follows."""
    from yoke_core.domain.agents_render_context import expand_markers
    from yoke_core.domain.agents_render_field_note import (
        expand_field_note_markers,
    )

    rendered = render_claude_agent("architect", target_root=repo_root)
    assert rendered.startswith("---\n"), "Must start with YAML frontmatter delimiter"
    second_delim = rendered.index("---\n", 4)
    assert second_delim > 4, "Must have a closing --- delimiter"
    after = rendered[second_delim + 4 :]
    assert after.startswith("\n"), "Body must be separated from frontmatter by a blank line"
    expanded = expand_field_note_markers(
        expand_markers(load_canonical("architect", target_root=repo_root))
    ).lstrip("\n")
    assert expanded in rendered


def test_render_deterministic(repo_root: Path) -> None:
    """Two calls produce identical bytes."""
    first = render_claude_agent("architect", target_root=repo_root)
    second = render_claude_agent("architect", target_root=repo_root)
    assert first == second, "Rendering must be deterministic"


def test_detect_drift_on_divergence(
    temp_agent_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inject divergence into a temp checkout, confirm drift is reported."""
    root = temp_agent_env
    monkeypatch.setattr("yoke_core.domain.agents_render.AGENTS", ["architect"])

    # Write the "correct" rendered output first
    rendered = render_claude_agent("architect", target_root=root)
    out_path = root / CLAUDE_OUT_DIR / "yoke-architect.md"
    out_path.write_text(rendered)

    # Now corrupt the on-disk agent file
    out_path.write_text("CORRUPTED CONTENT")

    drifted = detect_drift(target_root=root)

    assert any("yoke-architect.md" in d for d in drifted), (
        f"Expected drift report for architect, got: {drifted}"
    )


def test_detect_drift_clean(
    temp_agent_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Against matching content, drift list is empty."""
    root = temp_agent_env
    monkeypatch.setattr("yoke_core.domain.agents_render.AGENTS", ["architect"])

    # Write matching file
    out_path = root / CLAUDE_OUT_DIR / "yoke-architect.md"
    out_path.write_text(render_claude_agent("architect", target_root=root))

    drifted = detect_drift(target_root=root)

    assert drifted == [], f"Expected no drift, got: {drifted}"


def test_byte_identity(repo_root: Path) -> None:
    """Each rendered agent matches on-disk runtime/harness/claude/agents/yoke-{agent}.md."""
    for agent in AGENTS:
        rendered = render_claude_agent(agent, target_root=repo_root)
        on_disk_path = repo_root / CLAUDE_OUT_DIR / f"yoke-{agent}.md"
        assert on_disk_path.exists(), f"Missing on-disk file: {on_disk_path}"
        on_disk = on_disk_path.read_text(encoding="utf-8")
        assert rendered == on_disk, f"Byte mismatch for {agent}"


def test_dry_run_no_write(repo_root: Path) -> None:
    """dry_run=True must not modify any file on disk."""
    target = repo_root / CLAUDE_OUT_DIR / "yoke-architect.md"
    mtime_before = target.stat().st_mtime_ns if target.exists() else None

    results = write_all_claude(target_root=repo_root, dry_run=True)

    # Verify at least one path in results
    assert len(results) > 0

    if target.exists():
        mtime_after = target.stat().st_mtime_ns
        assert mtime_before == mtime_after, "dry_run must not modify files"


def test_load_claude_spec_key_order(repo_root: Path) -> None:
    """load_claude_spec returns keys in CLAUDE_SPEC_KEY_ORDER."""
    spec = load_claude_spec("architect", target_root=repo_root)
    keys = list(spec.keys())
    # All returned keys must appear in order within CLAUDE_SPEC_KEY_ORDER
    order_indices = [CLAUDE_SPEC_KEY_ORDER.index(k) for k in keys]
    assert order_indices == sorted(order_indices), (
        f"Keys not in canonical order: {keys}"
    )


def test_all_agents_renderable(repo_root: Path) -> None:
    """Every agent in AGENTS can be rendered without error."""
    for agent in AGENTS:
        rendered = render_claude_agent(agent, target_root=repo_root)
        assert "---\n" in rendered
        assert len(rendered) > 100


def test_no_rendered_agent_uses_retired_backlog_md_paths(repo_root: Path) -> None:
    """Canonical bodies and rendered adapters must not reference yoke/backlog/."""
    for agent in AGENTS:
        canonical = load_canonical(agent, target_root=repo_root)
        rendered = render_claude_agent(agent, target_root=repo_root)
        assert "runtime/backlog/" not in canonical, f"{agent}: stale runtime/backlog/ ref in canonical"
        assert "runtime/backlog/" not in rendered, f"{agent}: stale runtime/backlog/ ref in rendered"
        assert "data/backlog/" not in canonical, f"{agent}: retired data/backlog/ ref in canonical"
        assert "data/backlog/" not in rendered, f"{agent}: retired data/backlog/ ref in rendered"


def test_tester_browser_reference_is_committed_symlink(repo_root: Path) -> None:
    """runtime/harness/claude/agents/references/yoke-tester-browser.md is a symlink
    to the canonical runtime/agents/tester-browser.md — not a rendered copy."""
    ref_path = repo_root / CLAUDE_OUT_DIR / "references" / "yoke-tester-browser.md"
    assert ref_path.is_symlink(), f"{ref_path} must be a symlink, not a rendered copy"
    resolved = ref_path.resolve()
    expected = (repo_root / CANONICAL_DIR / "tester-browser.md").resolve()
    assert resolved == expected, (
        f"tester-browser reference resolves to {resolved}, expected {expected}"
    )


# Marker-expansion tests live in `test_agents_render_context.py`.


def test_detect_substrate_drift_flags_stale_term_with_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a canonical body carries packet markers AND a hand-authored
    stale snippet, `detect_substrate_drift` must report a `stale-term:`
    drift entry. The presence of the marker means the agent already gets
    the generated packet; an additional stale example is exactly the
    kind of duplication AC-8 forbids."""

    from yoke_core.domain.agents_render import (
        CANONICAL_DIR,
        detect_substrate_drift,
    )

    repo = tmp_path
    canonical = repo / CANONICAL_DIR
    canonical.mkdir(parents=True)
    # qa_kind='review' is in seed.STALE_TERMS and is what AC-7 / AC-18
    # specifically forbid in rendered Tester adapters.
    bad_term = "qa_kind=" "'review'"
    (canonical / "tester.md").write_text(
        "Tester body.\n"
        "<!-- YOKE:DB-PACKET role=tester_agent topic=qa start -->\n"
        "<!-- YOKE:DB-PACKET end -->\n"
        f"\nLegacy snippet still mentions {bad_term} in prose.\n",
        encoding="utf-8",
    )
    (canonical / "tester.claude.json").write_text(
        '{"name": "yoke-tester", "description": "x", "tools": "Read"}',
        encoding="utf-8",
    )
    (canonical / "tester.codex.json").write_text(
        '{"name": "yoke-tester", "description": "x"}',
        encoding="utf-8",
    )
    monkeypatch.setattr("yoke_core.domain.agents_render.AGENTS", ["tester"])
    drift = detect_substrate_drift(target_root=repo)
    assert any("stale-term:" in d and "tester.md" in d for d in drift), (
        f"expected stale-term drift entry for tester.md, got: {drift}"
    )


def test_detect_substrate_drift_flags_unmatched_conditional_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3: an unmatched YOKE:HARNESS start marker must surface as a
    drift entry from the universal substrate drift surface so the existing
    HC-harness-substrate-drift health check catches it.
    """
    from yoke_core.domain.agents_render import (
        CANONICAL_DIR,
        detect_substrate_drift,
    )

    repo = tmp_path
    canonical = repo / CANONICAL_DIR
    canonical.mkdir(parents=True)
    (canonical / "tester.md").write_text(
        "Tester body.\n"
        "<!-- YOKE:HARNESS claude start -->\n"
        "orphan claude content (no end marker)\n",
        encoding="utf-8",
    )
    (canonical / "tester.claude.json").write_text(
        '{"name": "yoke-tester", "description": "x", "tools": "Read"}',
        encoding="utf-8",
    )
    (canonical / "tester.codex.json").write_text(
        '{"name": "yoke-tester", "description": "x"}',
        encoding="utf-8",
    )
    monkeypatch.setattr("yoke_core.domain.agents_render.AGENTS", ["tester"])
    drift = detect_substrate_drift(target_root=repo)
    assert any(
        d.startswith("conditional-marker: ") and "tester.md" in d for d in drift
    ), f"expected conditional-marker drift entry for tester.md, got: {drift}"
    assert any("line 2" in d for d in drift), (
        f"expected conditional marker drift to name the source line, got: {drift}"
    )


def test_codex_adapters_emit_no_tools_field() -> None:
    """AC-2 / AC-15: Codex adapter metadata carries no `tools` field — the
    Claude-only allowlist (Monitor included) has no Codex subagent meaning."""
    from yoke_core.domain.agents_render import CANONICAL_DIR
    from yoke_core.domain.agents_render_codex import render_codex_agent

    checkout_root = Path(__file__).resolve().parents[3]
    canonical_dir = checkout_root / CANONICAL_DIR
    for agent in ("engineer", "tester"):
        rendered = render_codex_agent(canonical_dir, agent)
        header = rendered.split('developer_instructions = """', 1)[0]
        tools_lines = [
            line for line in header.splitlines()
            if line.lstrip().startswith("tools")
        ]
        assert not tools_lines, (
            f"Codex adapter for {agent} still emits a tools field: {tools_lines}"
        )


# AC-5 cross-cwd regression test lives in test_agents_render_workspace_anchor.py.
