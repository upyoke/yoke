"""Tests for the universal harness substrate renderer.

Covers the universal substrate extension that renders Claude
``settings.json``/``manifest.json``, Codex ``hooks.json``/``manifest.json``,
and the Codex agent ``.toml`` tree from canonical Yoke source. The
legacy Claude agent-render surface (``.md`` adapters) is covered by
``test_agents_render.py``.

Behavior covered: drift check + idempotency, the eight Codex agents,
embedded subdir fragments, per-output render coverage, the
do-not-hand-edit marker, and the absence of a second
canonical Codex prompt body.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain.agents_render import (
    AGENTS,
    CANONICAL_DIR,
    CODEX_NATIVE_AGENTS_DIR,
    CODEX_OUT_DIR,
    ROLES_WITH_INLINE_REFERENCES,
    detect_substrate_drift,
    write_all,
)
from yoke_core.domain.agents_render_references import inline_fragment_paths
from yoke_core.domain.agents_render_claude import (
    render_claude_manifest_json,
    render_claude_settings_json,
)
from yoke_core.domain.agents_render_codex import (
    render_codex_agent_body,
    render_codex_hooks_json,
    render_codex_manifest_json,
)


@pytest.fixture
def repo_root() -> Path:
    """Workspace-anchored live checkout for read-only assertions."""
    from runtime.api.domain.test_agents_render_workspace_fixtures import (
        resolve_live_repo_root,
    )

    return resolve_live_repo_root()


@pytest.fixture
def isolated_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tmp_path-backed canonical tree for tests that exercise ``write_all``.

    Patches ``AGENTS`` to a single role so the fixture stays small.
    """
    canonical = tmp_path / CANONICAL_DIR
    canonical.mkdir(parents=True)
    claude_spec = '{"name": "yoke-architect", "description": "x", "tools": "Read"}'
    codex_spec = '{"name": "yoke-architect", "description": "x"}'
    cursor_spec = '{"name": "yoke-architect", "description": "x"}'
    (canonical / "architect.md").write_text("# canonical body\n", encoding="utf-8")
    (canonical / "architect.claude.json").write_text(claude_spec, encoding="utf-8")
    (canonical / "architect.codex.json").write_text(codex_spec, encoding="utf-8")
    (canonical / "architect.cursor.json").write_text(cursor_spec, encoding="utf-8")
    monkeypatch.setattr("yoke_core.domain.agents_render.AGENTS", ["architect"])
    return tmp_path


# ---------------------------------------------------------------------------
# Codex agent .toml tree
# ---------------------------------------------------------------------------


def test_render_codex_agent_tree_present(repo_root: Path) -> None:
    """Every Yoke agent has a rendered Codex .toml adapter on disk."""
    for agent in AGENTS:
        out = repo_root / CODEX_OUT_DIR / f"yoke-{agent}.toml"
        assert out.exists(), f"missing rendered Codex adapter for {agent}: {out}"


def test_codex_agent_runtime_path_is_surfaced_to_native_location(
    repo_root: Path,
) -> None:
    """Codex dispatch descriptors name the native ``.codex/agents`` path."""
    native_dir = repo_root / CODEX_NATIVE_AGENTS_DIR
    rendered_dir = repo_root / CODEX_OUT_DIR

    assert native_dir.is_symlink(), f"missing .codex/agents symlink: {native_dir}"
    assert native_dir.resolve() == rendered_dir.resolve()

    for agent in AGENTS:
        assert (native_dir / f"yoke-{agent}.toml").is_file(), (
            f"native Codex adapter path missing {agent}"
        )


def test_render_codex_agent_body_includes_unconditional_references(
    repo_root: Path,
) -> None:
    """Always-needed role references are embedded into the prompt."""
    canonical = repo_root / CANONICAL_DIR
    for role in ROLES_WITH_INLINE_REFERENCES:
        with patch(
            "yoke_core.domain.schema_api_context._try_live_schema", return_value=None
        ):
            body = render_codex_agent_body(canonical, role)
        fragments = inline_fragment_paths(canonical, role)
        assert fragments, f"{role}: expected inline references"
        for frag in fragments:
            text = frag.read_text(encoding="utf-8")
            marker = next((line for line in text.splitlines() if line.strip()), "")
            assert marker and marker in body, (
                f"{role}: reference {frag.name} marker {marker!r} not embedded"
            )


def test_no_codex_canonical_md_exists(repo_root: Path) -> None:
    """The Codex adapter must not have a parallel `.codex.md` canonical body.

    The Codex prompt sources entirely from `runtime/agents/{role}.md` plus the
    role's subdir fragments — no second canonical body is allowed.
    """
    canonical = repo_root / CANONICAL_DIR
    stray = sorted(canonical.glob("*.codex.md"))
    assert stray == [], f"stray .codex.md canonical bodies present: {stray}"


def test_render_emits_eight_codex_agents() -> None:
    """AGENTS contains exactly the eight primary Yoke agents."""
    expected = {
        "architect",
        "boss",
        "engineer",
        "product-designer",
        "product-manager",
        "qa-walker",
        "simulator",
        "tester",
    }
    assert set(AGENTS) == expected
    assert len(AGENTS) == 8


# ---------------------------------------------------------------------------
# Hook + manifest content
# ---------------------------------------------------------------------------


def test_render_codex_hooks_json_matches_strict_schema_and_matchers() -> None:
    """Rendered Codex hooks.json keeps schema-strict top-level keys and matchers."""
    rendered = render_codex_hooks_json()
    payload = json.loads(rendered)
    assert set(payload) == {"hooks"}
    hooks = payload["hooks"]
    assert any(
        e.get("matcher") == "apply_patch|Write|Edit"
        for e in hooks.get("PreToolUse", [])
    )
    assert any(
        e.get("matcher") == "apply_patch|Write|Edit"
        for e in hooks.get("PermissionRequest", [])
    )
    assert any(
        e.get("matcher") == "apply_patch|Write|Edit"
        for e in hooks.get("PostToolUse", [])
    )


def test_render_claude_settings_json_has_generated_marker_and_hooks() -> None:
    """Rendered Claude settings.json carries marker, hooks, permissions."""
    rendered = render_claude_settings_json()
    payload = json.loads(rendered)
    assert "_generated" in payload
    assert "do not hand-edit" in payload["_generated"]
    assert "hooks" in payload and isinstance(payload["hooks"], dict)
    assert "permissions" in payload and "allow" in payload["permissions"]
    assert "Write(**)" not in payload["permissions"]["allow"]
    assert "Edit(**)" in payload["permissions"]["allow"]
    assert payload.get("autoMemoryEnabled") is False
    # Every PreToolUse entry routes through the stable Yoke CLI; the
    # per-policy chain (lint_session_cwd, etc.) is dispatched inside the
    # runner behind that boundary, not enumerated in the manifest.
    pre = payload["hooks"].get("PreToolUse", [])
    cmds = [h["command"] for e in pre for h in e.get("hooks", [])]
    assert cmds and all("yoke hook evaluate PreToolUse" in c for c in cmds), (
        f"expected yoke hook evaluate PreToolUse on every entry, got: {cmds}"
    )


def test_render_claude_manifest_has_generated_marker_and_schema_keys() -> None:
    """Rendered Claude manifest carries marker and schema keys."""
    rendered = render_claude_manifest_json()
    payload = json.loads(rendered)
    assert "_generated" in payload
    assert payload.get("harness_id") == "claude-code"
    for key in (
        "runtime_minimums",
        "bootstrap",
        "identity",
        "supports",
        "telemetry",
        "fallback",
        "canonical_agents",
    ):
        assert key in payload, f"manifest missing schema key {key!r}"


def test_render_codex_manifest_has_generated_marker_and_no_legacy_terms() -> None:
    """Rendered Codex manifest carries marker, drops metadata-only/bash_*_hook."""
    rendered = render_codex_manifest_json()
    assert "metadata-only" not in rendered
    assert "bash_pre_tool_hook" not in rendered
    assert "bash_post_tool_hook" not in rendered
    payload = json.loads(rendered)
    assert "_generated" in payload
    assert payload["harness_id"] == "codex"
    assert payload["canonical_agents"]["consumption"] == "generated"


# ---------------------------------------------------------------------------
# Drift detection + idempotency
# ---------------------------------------------------------------------------


def test_check_passes_after_render(isolated_repo: Path) -> None:
    """Drift check exits 0 immediately after a render against an isolated repo."""
    write_all(target_root=isolated_repo, dry_run=False)
    drifted = detect_substrate_drift(target_root=isolated_repo)
    assert drifted == [], f"drift after render: {drifted}"


def test_render_is_idempotent(isolated_repo: Path) -> None:
    """Re-rendering produces no changes when on-disk matches universal source."""
    first = write_all(target_root=isolated_repo, dry_run=False)
    second = write_all(target_root=isolated_repo, dry_run=False)
    not_skipped = {p: a for p, (a, _) in second.items() if a != "skip"}
    assert not_skipped == {}, (
        f"second render must be a no-op, got non-skip actions: {not_skipped} "
        f"(first pass: {[p for p, (a, _) in first.items() if a != 'skip']})"
    )


def test_substrate_drift_clean_baseline(isolated_repo: Path) -> None:
    """Against a freshly rendered substrate, ``detect_substrate_drift`` is empty."""
    write_all(target_root=isolated_repo, dry_run=False)
    assert detect_substrate_drift(target_root=isolated_repo) == []


def _seed_minimal_canonical_tree(repo: Path) -> None:
    canonical = repo / CANONICAL_DIR
    canonical.mkdir(parents=True)
    claude_spec = '{"name": "yoke-architect", "description": "x", "tools": "Read"}'
    codex_spec = '{"name": "yoke-architect", "description": "x"}'
    cursor_spec = '{"name": "yoke-architect", "description": "x"}'
    (canonical / "architect.md").write_text("# canonical body\n", encoding="utf-8")
    (canonical / "architect.claude.json").write_text(claude_spec)
    (canonical / "architect.codex.json").write_text(codex_spec)
    (canonical / "architect.cursor.json").write_text(cursor_spec)


def test_drift_detection_reports_handedited_file(tmp_path: Path) -> None:
    """Hand-edit a rendered file in a tmpdir copy; detect_substrate_drift surfaces it."""
    _seed_minimal_canonical_tree(tmp_path)
    with patch("yoke_core.domain.agents_render.AGENTS", ["architect"]):
        write_all(target_root=tmp_path, dry_run=False)
        target = tmp_path / CODEX_OUT_DIR / "yoke-architect.toml"
        target.write_text("# CORRUPTED — not rendered output\n", encoding="utf-8")
        drift = detect_substrate_drift(target_root=tmp_path)
    assert any("yoke-architect.toml" in d for d in drift), (
        f"expected drift entry for hand-edited toml, got: {drift}"
    )


def _tools_set(spec: dict) -> set[str]:
    raw = spec.get("tools") or ""
    if isinstance(raw, list):
        return {str(t).strip() for t in raw if t}
    return {token.strip() for token in str(raw).split(",") if token.strip()}


def test_pm_pd_sidecars_have_no_bash_in_either_harness(repo_root: Path) -> None:
    """Product Manager and Product Designer never grant Bash in adapters."""

    canonical = repo_root / "runtime/agents"
    for agent in ("product-manager", "product-designer"):
        for ext in ("claude.json", "codex.json"):
            spec = json.loads((canonical / f"{agent}.{ext}").read_text("utf-8"))
            assert "Bash" not in _tools_set(spec), (
                f"{agent}.{ext} grants Bash; PM/PD must remain non-Bash"
            )
    claude_dir = repo_root / "runtime/harness/claude/agents"
    codex_dir = repo_root / "runtime/harness/codex/agents"
    for agent in ("product-manager", "product-designer"):
        claude_text = (claude_dir / f"yoke-{agent}.md").read_text("utf-8")
        # Frontmatter ``tools:`` line lists comma-separated grants. The
        # ``disallowedTools:`` line is a different field and may include
        # ``Bash`` — that is the explicit deny half of the tool policy and must not
        # trip the assertion.
        tools_line = next(
            (line for line in claude_text.splitlines() if line.startswith("tools:")), ""
        )
        assert tools_line, f"yoke-{agent}.md missing tools: line"
        assert "Bash" not in tools_line, (
            f"rendered Claude adapter for {agent} grants Bash on tools line"
        )
        # Codex emits no tools field; the Claude allowlist has no Codex meaning.
        codex_text = (codex_dir / f"yoke-{agent}.toml").read_text("utf-8")
        codex_header = codex_text.split('developer_instructions = """', 1)[0]
        has_tools = any(
            line.lstrip().startswith("tools") for line in codex_header.splitlines()
        )
        assert not has_tools, f"rendered Codex adapter for {agent} still emits tools"


def test_bash_capable_actors_have_packet_markers(repo_root: Path) -> None:
    """Any agent granting Bash must carry generated packet markers."""
    canonical = repo_root / "runtime/agents"
    marker = "<!-- YOKE:DB-PACKET role="
    for agent in AGENTS:
        spec = json.loads((canonical / f"{agent}.claude.json").read_text("utf-8"))
        if "Bash" not in _tools_set(spec):
            continue
        body = (canonical / f"{agent}.md").read_text("utf-8")
        assert marker in body, f"Bash-capable agent {agent!r} has no packet markers"


def test_drift_detection_reports_missing_codex_native_symlink(tmp_path: Path) -> None:
    """The drift gate covers Codex's native custom-agent discovery path."""
    _seed_minimal_canonical_tree(tmp_path)
    with patch("yoke_core.domain.agents_render.AGENTS", ["architect"]):
        write_all(target_root=tmp_path, dry_run=False)
        native_dir = tmp_path / CODEX_NATIVE_AGENTS_DIR
        assert native_dir.is_symlink()
        native_dir.unlink()
        drift = detect_substrate_drift(target_root=tmp_path)
    assert any(str(CODEX_NATIVE_AGENTS_DIR) in d for d in drift), (
        f"expected drift entry for missing native symlink, got: {drift}"
    )
