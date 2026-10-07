"""Create-help teaching: candidate membership is checked before run creation."""

from __future__ import annotations

from yoke_contracts.deployment_itemless_teaching import CREATE_DESCRIPTION
from yoke_contracts.deployment_release_roles_teaching import RELEASE_ROLE_RECIPE


def test_create_description_does_not_route_item_bound_batch_to_start_for_item() -> None:
    lowered = CREATE_DESCRIPTION.lower()
    assert "start-for-item" not in lowered
    assert "item-bound" in lowered
    assert "create-then-watch" in lowered


def test_create_description_states_composition_precedes_run_commit() -> None:
    assert "created" in CREATE_DESCRIPTION
    assert "provisionally composes membership" in CREATE_DESCRIPTION
    assert "before committing a run ID" in CREATE_DESCRIPTION
    assert "candidate" in CREATE_DESCRIPTION


def test_create_description_teaches_that_a_held_item_is_skipped_by_name() -> None:
    """An operator must be able to tell "left out" from "refused"."""
    assert "already holds is not composed" in CREATE_DESCRIPTION
    assert "naming the run that holds it" in CREATE_DESCRIPTION


def test_create_description_teaches_stage_custody_follows_the_commit() -> None:
    assert "production run on the same commit holds" in CREATE_DESCRIPTION
    assert "pinned a different commit, naming that commit" in CREATE_DESCRIPTION


def test_release_role_recipe_teaches_validate_composition_composes_now() -> None:
    assert "optional preview" not in RELEASE_ROLE_RECIPE
    assert "composes the run now" in RELEASE_ROLE_RECIPE
