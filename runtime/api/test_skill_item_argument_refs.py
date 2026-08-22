"""Skill recipes preserve public item references at operator boundaries."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
CANONICAL = ROOT / ".agents/skills/yoke"
BUNDLE = (
    ROOT
    / "packages/yoke-core/src/yoke_core/install_bundle_tree/.agents/skills/yoke"
)

SKILL_PATHS = (
    Path("advance/SKILL.md"),
    Path("feed/gather.md"),
    Path("feed/materialize.md"),
    Path("polish/review.md"),
    Path("refine/SKILL.md"),
    Path("refine/review-rubric.md"),
    Path("simulate/SKILL.md"),
    Path("usher/deploy.md"),
    Path("usher/merge.md"),
    Path("usher/plan.md"),
)

LEGACY_ARGUMENT_PATTERNS = (
    re.compile(r"PREFIX-\{(?:N|id|item_id)\}"),
    re.compile(r"--item(?:-id)?\s+\{(?:N|id|item_id)\}"),
    re.compile(r"done-transition[^\n`]*--\s+\{(?:N|id|item_id)\}"),
)


@pytest.mark.parametrize("relative_path", SKILL_PATHS, ids=str)
def test_item_recipe_skill_matches_install_bundle(relative_path: Path) -> None:
    assert (CANONICAL / relative_path).read_bytes() == (
        BUNDLE / relative_path
    ).read_bytes()


@pytest.mark.parametrize("relative_path", SKILL_PATHS, ids=str)
def test_item_recipe_skill_uses_prefix_neutral_public_examples(
    relative_path: Path,
) -> None:
    content = (CANONICAL / relative_path).read_text()

    assert "PREFIX-N" in content
    for legacy_pattern in LEGACY_ARGUMENT_PATTERNS:
        assert legacy_pattern.search(content) is None


def test_done_transition_and_event_recipes_pass_public_item_refs() -> None:
    deploy = (CANONICAL / "usher/deploy.md").read_text()
    merge = (CANONICAL / "usher/merge.md").read_text()
    simulate = (CANONICAL / "simulate/SKILL.md").read_text()

    assert "done-transition -- PREFIX-N --skip-deploy" in deploy
    assert "yoke events query --event-name MergeEngineFailed --item PREFIX-N" in merge
    assert "yoke events query --item PREFIX-N" in simulate
