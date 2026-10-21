"""Registry checks for Codex capability surfaces.

The shared Yoke registry is the capability source.
"""

from __future__ import annotations

from yoke_contracts.skill_registry import SKILLS_BY_ID, STAGE_SKILL_IDS
from yoke_core.domain.harness_capability_registry import (
    compact_entrypoint_display,
    safe_operator_surface_entrypoints,
    shared_downstream_paths,
    shared_entrypoints,
)


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
