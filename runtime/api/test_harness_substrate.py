"""Third-harness fixture test — proves universal Yoke source stays harness-agnostic.

Structural regression: register a fake ``"test-harness"`` in test scope, render
canonical Yoke source against an isolated tmp repo, and assert that:

1. The capability registry's ``safe_operator_surface_for_harness`` returns the
   universal command list when the harness universe includes ``"test-harness"``
   (i.e. no ``if harness_id == "claude-code"`` shortcut leaks into the
   registry's lookup function).
2. The renderer writes Claude + Codex outputs under the fixture's expected
   output dir (the patched repo root) — proving the renderer doesn't hardcode
   the absolute repo path.
3. No parallel canonical prompt body is created for ``"test-harness"`` —
   universal Yoke source remains the single source of truth for agent
   bodies.

If a hardcoded ``if harness_id == "claude-code"`` or ``if harness_id == "codex"``
branch leaks into universal source and breaks the fixture, the test fails with
a message naming the offending behavior. Satisfies FR-11 / AC-16.

Future third-harness onboarding consumes this fixture as the proof template;
the fixture artifacts live at ``runtime/api/test_fixtures/test_harness_adapter/``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import harness_capability_registry as registry
from yoke_core.domain.agents_render import (
    CANONICAL_DIR,
    CLAUDE_OUT_DIR,
    CODEX_OUT_DIR,
    write_all,
)
from yoke_core.domain.harness_capability_registry import (
    HARNESS_UNIVERSE,
    SAFE_OPERATOR_SURFACE,
    safe_operator_surface_for_harness,
)


FIXTURE_HARNESS_ID = "test-harness"
FIXTURE_DIR = Path(__file__).parent / "test_fixtures" / "test_harness_adapter"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_manifest() -> dict:
    """Load the fixture's stub manifest from disk."""
    return json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture
def fixture_sidecar() -> dict:
    """Load the fixture's per-harness adapter metadata sidecar."""
    return json.loads(
        (FIXTURE_DIR / f"{FIXTURE_HARNESS_ID}.codex.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def extended_universe(monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    """Extend ``HARNESS_UNIVERSE`` to include ``test-harness`` for the test scope.

    Also rebuilds ``SAFE_OPERATOR_SURFACE`` so existing default-supported
    commands (the rows whose ``harness_support`` matches the original
    universe) carry the extended tuple — proving the registry stays
    harness-agnostic when a third harness joins. Cleanup is automatic via
    monkeypatch.
    """
    extended = HARNESS_UNIVERSE + (FIXTURE_HARNESS_ID,)
    monkeypatch.setattr(registry, "HARNESS_UNIVERSE", extended)

    rebuilt = tuple(
        replace(cmd, harness_support=extended)
        if cmd.harness_support == HARNESS_UNIVERSE
        else cmd
        for cmd in SAFE_OPERATOR_SURFACE
    )
    monkeypatch.setattr(registry, "SAFE_OPERATOR_SURFACE", rebuilt)
    return extended


@pytest.fixture
def isolated_repo(tmp_path: Path) -> Path:
    """Build a minimal canonical source tree under ``tmp_path``.

    Mirrors the isolation pattern used by ``test_agents_render_substrate.py``:
    one minimal agent, both per-harness sidecars, and the harness output
    directories already present so ``write_all`` can land its outputs.
    """
    canonical = tmp_path / CANONICAL_DIR
    canonical.mkdir(parents=True)
    (canonical / "architect.md").write_text("# canonical architect body\n", encoding="utf-8")
    (canonical / "architect.claude.json").write_text(
        '{"name": "yoke-architect", "description": "fixture architect", "tools": "Read"}',
        encoding="utf-8",
    )
    (canonical / "architect.codex.json").write_text(
        '{"name": "yoke-architect", "description": "fixture architect"}',
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Registry-level proof: safe_operator_surface_for_harness is harness-agnostic
# ---------------------------------------------------------------------------


def test_fixture_manifest_declares_test_harness(fixture_manifest: dict) -> None:
    """The fixture manifest names ``test-harness`` and uses the shared registry.

    Establishes the contract the proof rests on: a hypothetical third harness
    can declare ``command_source: shared_yoke_registry`` and pick up the
    universal command list without registry edits.
    """
    assert fixture_manifest["harness_id"] == FIXTURE_HARNESS_ID
    assert fixture_manifest["supports"]["command_source"] == "shared_yoke_registry"
    assert fixture_manifest["supports"]["disabled_entrypoints"] == []
    assert fixture_manifest["supports"]["disabled_downstream_paths"] == []


def test_extended_universe_includes_test_harness(extended_universe: tuple[str, ...]) -> None:
    """The monkey-patched universe carries ``test-harness`` alongside the originals."""
    assert FIXTURE_HARNESS_ID in extended_universe
    for original in HARNESS_UNIVERSE:
        assert original in extended_universe, (
            f"original harness {original!r} dropped from extended universe"
        )


def test_safe_operator_surface_returns_universal_commands_for_test_harness(
    extended_universe: tuple[str, ...],
) -> None:
    """AC-4 + AC-6: the lookup is harness-id-agnostic.

    With ``HARNESS_UNIVERSE`` and ``SAFE_OPERATOR_SURFACE`` patched to include
    ``test-harness``, the lookup returns the same command list as for the
    originally-recognised harnesses' default-supported commands. If a future
    edit adds ``if harness_id == "claude-code"`` (or any specific id) to
    ``safe_operator_surface_for_harness``, this assertion fails because the
    fixture harness drops out.
    """
    test_harness_cmds = safe_operator_surface_for_harness(FIXTURE_HARNESS_ID)
    claude_cmds = safe_operator_surface_for_harness("claude-code")

    test_harness_entrypoints = {c.entrypoint for c in test_harness_cmds}
    claude_entrypoints = {c.entrypoint for c in claude_cmds}

    assert test_harness_entrypoints == claude_entrypoints, (
        f"test-harness must see the same default-supported commands as claude-code; "
        f"diff (claude-only): {claude_entrypoints - test_harness_entrypoints}, "
        f"(test-harness-only): {test_harness_entrypoints - claude_entrypoints}. "
        f"Likely cause: a hardcoded harness-id branch in "
        f"yoke_core.domain.harness_capability_registry."
    )
    assert test_harness_cmds, "expected at least one universal command for test-harness"


def test_opt_out_command_does_not_leak_into_test_harness(
    extended_universe: tuple[str, ...],
) -> None:
    """A row that explicitly opts OUT of the universe must not leak to test-harness.

    Defends against the inverse failure mode: a literal ``return all_commands``
    in ``safe_operator_surface_for_harness`` that ignores ``harness_support``.
    The test injects an opt-out row for the duration of the assertion.
    """
    opt_out_cmd = registry.OperatorCommand(
        entrypoint="/yoke opt-out-fixture",
        display="/yoke opt-out-fixture",
        reminder="  fixture-only opt-out — never reachable",
        harness_support=("claude-code",),
    )
    augmented = registry.SAFE_OPERATOR_SURFACE + (opt_out_cmd,)
    with patch.object(registry, "SAFE_OPERATOR_SURFACE", augmented):
        test_harness_cmds = safe_operator_surface_for_harness(FIXTURE_HARNESS_ID)
        claude_cmds = safe_operator_surface_for_harness("claude-code")

    test_harness_entrypoints = {c.entrypoint for c in test_harness_cmds}
    claude_entrypoints = {c.entrypoint for c in claude_cmds}

    assert "/yoke opt-out-fixture" in claude_entrypoints
    assert "/yoke opt-out-fixture" not in test_harness_entrypoints, (
        "opt-out command leaked to test-harness; "
        "safe_operator_surface_for_harness ignores harness_support"
    )


# ---------------------------------------------------------------------------
# Renderer-level proof: writes land under the fixture's expected output dir
# ---------------------------------------------------------------------------


def test_renderer_writes_under_fixture_output_dir(isolated_repo: Path) -> None:
    """AC-3: rendered output appears under the fixture's expected directory.

    The fixture's "expected directory" is the harness output tree relative to
    the patched repo root (``tmp_path``). The renderer is harness-agnostic at
    the path level: every output path is computed relative to ``_repo_root()``,
    so patching ``_repo_root`` to ``tmp_path`` redirects every write under
    ``tmp_path/runtime/harness/...``. No write touches the real repo's
    ``runtime/harness/`` tree.
    """
    real_claude_dir = Path(__file__).resolve().parents[2] / CLAUDE_OUT_DIR
    real_claude_mtimes_before = {
        p.name: p.stat().st_mtime for p in real_claude_dir.glob("*.md")
    }

    with patch("yoke_core.domain.agents_render.AGENTS", ["architect"]):
        write_all(target_root=isolated_repo, dry_run=False)

    fixture_claude_md = isolated_repo / CLAUDE_OUT_DIR / "yoke-architect.md"
    fixture_codex_toml = isolated_repo / CODEX_OUT_DIR / "yoke-architect.toml"
    assert fixture_claude_md.exists(), (
        f"renderer did not write Claude adapter under fixture output dir: {fixture_claude_md}"
    )
    assert fixture_codex_toml.exists(), (
        f"renderer did not write Codex adapter under fixture output dir: {fixture_codex_toml}"
    )

    real_claude_mtimes_after = {
        p.name: p.stat().st_mtime for p in real_claude_dir.glob("*.md")
    }
    assert real_claude_mtimes_before == real_claude_mtimes_after, (
        "renderer wrote into the real runtime/harness/claude/agents/ tree; "
        "target_root=isolated_repo did not isolate the output root"
    )


def test_no_test_harness_canonical_body_emitted(isolated_repo: Path) -> None:
    """AC-8 reused for the fixture: no second canonical prompt body is created.

    The renderer must not synthesise ``runtime/agents/architect.test-harness.md``
    or any analogue. Universal Yoke source remains the single source of truth
    for agent bodies; per-harness adapter metadata lives in JSON sidecars only.
    """
    with patch("yoke_core.domain.agents_render.AGENTS", ["architect"]):
        write_all(target_root=isolated_repo, dry_run=False)

    canonical = isolated_repo / CANONICAL_DIR
    forbidden = list(canonical.glob(f"*.{FIXTURE_HARNESS_ID}.md"))
    assert not forbidden, (
        f"renderer emitted a parallel canonical body for {FIXTURE_HARNESS_ID}: {forbidden}"
    )

    fixture_subtree = isolated_repo / "runtime" / "harness" / FIXTURE_HARNESS_ID
    assert not fixture_subtree.exists(), (
        f"renderer emitted a third-harness adapter tree without registry plumbing: "
        f"{fixture_subtree} should not exist (the renderer is hardcoded for "
        f"claude-code + codex; future plug-in support is out of scope for this fixture)"
    )


# ---------------------------------------------------------------------------
# Sidecar shape: empty per-harness adapter metadata is well-formed JSON
# ---------------------------------------------------------------------------


def test_fixture_sidecar_is_minimal_well_formed_json(fixture_sidecar: dict) -> None:
    """The empty sidecar at least carries ``name``+``description`` so future
    third-harness work has a starting shape to extend.
    """
    assert "name" in fixture_sidecar
    assert "description" in fixture_sidecar
