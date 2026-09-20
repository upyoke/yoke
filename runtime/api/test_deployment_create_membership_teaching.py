"""Create-help teaching: membership is filled from the candidate at start."""

from __future__ import annotations

from yoke_contracts.deployment_itemless_teaching import CREATE_DESCRIPTION
from yoke_contracts.deployment_release_roles_teaching import RELEASE_ROLE_RECIPE


def test_create_description_does_not_route_item_bound_batch_to_start_for_item() -> None:
    lowered = CREATE_DESCRIPTION.lower()
    assert "start-for-item" not in lowered
    assert "item-bound" in lowered
    assert "create-then-watch" in lowered


def test_create_description_states_enrolment_happens_at_start() -> None:
    assert "created" in CREATE_DESCRIPTION
    assert "fills it at the start" in CREATE_DESCRIPTION
    assert "candidate" in CREATE_DESCRIPTION


def test_release_role_recipe_teaches_validate_composition_composes_now() -> None:
    assert "optional preview" not in RELEASE_ROLE_RECIPE
    assert "composes the run now" in RELEASE_ROLE_RECIPE
