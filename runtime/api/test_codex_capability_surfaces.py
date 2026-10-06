"""Regression checks for Codex capability prose outside the primary docs.

The shared Yoke registry is the capability source. These checks cover
secondary operator surfaces that previously kept stale ``implement`` omissions
after the registry and main docs were corrected.

Note: collapsed Codex's session-lifecycle rendering into the shared
``yoke_core.hooks`` chain. The legacy
``ch._render_session_start_orientation`` / ``ch._render_prompt_submit_reminder``
helpers were deleted with the legacy ``codex_hooks`` module. The orientation
prose itself is now resolved through the runner's lifecycle dispatch and is
covered by ``runtime/harness/codex/SMOKE-TEST.md`` and the parity tests in
``runtime/harness/test_hook_runner_parity.py``. This file retains the
registry-based and doc-prose checks that survive the cutover.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.skill_registry import SKILLS_BY_ID, STAGE_SKILL_IDS
from yoke_core.domain.harness_capability_registry import (
    compact_entrypoint_display,
    safe_operator_surface_entrypoints,
    shared_downstream_paths,
    shared_entrypoints,
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repo root from test module location.")


REPO = _repo_root()


def _read(rel_path: str) -> str:
    path = REPO / rel_path
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


def test_codex_hook_orientation_lists_registry_implement_path():
    # Registry-based source-of-truth checks retained after the cutover.
    # The Codex per-event orientation rendering helpers were deleted with the
    # legacy ``codex_hooks`` module; the registry is the contract surface.
    assert SKILLS_BY_ID["implement"].display in compact_entrypoint_display()
    assert set(shared_downstream_paths()) == STAGE_SKILL_IDS


def test_conduct_is_shared_stage_and_safe_operator_surface():
    assert "/yoke conduct" in safe_operator_surface_entrypoints("codex")
    assert "/yoke conduct" in shared_entrypoints()
    assert "conduct" in shared_downstream_paths()


def test_direct_execution_paths_are_in_downstream_registry():
    paths = shared_downstream_paths()
    assert "dash" in paths
    assert "blitz" in paths


def test_codex_smoke_matrix_expects_implement_path():
    text = _read("runtime/harness/codex/SMOKE-TEST.md")

    assert "/yoke implement YOK-{N}" in text
    assert "implementation and review stay in the same worktree" in text
    assert "`implement` in supported_paths" in text
    assert "shepherd, refine, polish, usher" not in text


def test_hook_parity_map_matches_codex_shared_registry_summary():
    text = _read("docs/hook-parity-map.md")

    assert ("The skill registry supplies both capability views.") in text
    assert "safe operator surface" in text
    assert "downstream registry" in text
    assert "rather than copying either registry view" in text
    assert "/yoke implement" in text
    assert "/yoke conduct" in text
    assert "`implement`" in text
    assert "Conduct is a stage skill" in text
    assert "five entrypoints" not in text
    assert "four downstream paths" not in text


def test_command_references_teach_implement_and_internal_advance():
    for rel_path in (
        ".yoke/docs/reference/commands.md",
        ".agents/skills/yoke/SKILL.md",
        ".agents/skills/yoke/help/SKILL.md",
    ):
        text = _read(rel_path)
        # These files ship verbatim into target projects, so they teach the
        # generic ``PREFIX-N`` placeholder rather than this repo's item prefix.
        assert "/yoke implement PREFIX-N" in text
        assert "/yoke " + "advance PREFIX-N implementation" not in text
        assert "other than `implementation`" not in text
        assert "advance targets other than implementation" not in text
