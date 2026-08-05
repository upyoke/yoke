"""Taking an update must not mean discarding what a universe changed."""

from __future__ import annotations

from yoke_core.domain.workflow_canon_merge import merge_definitions

BASELINE = {
    "schema_version": 4,
    "policies": {"file_budget": "optional", "path_claims": "optional"},
    "entry_surfaces": ["harness_skill"],
}


def test_a_change_only_yoke_made_is_taken():
    theirs = {**BASELINE, "policies": {**BASELINE["policies"],
                                       "file_budget": "required"}}
    result = merge_definitions(BASELINE, dict(BASELINE), theirs)

    assert result.clean
    assert result.definition["policies"]["file_budget"] == "required"
    assert "policies.file_budget" in result.taken


def test_a_change_only_the_universe_made_is_kept():
    mine = {**BASELINE, "policies": {**BASELINE["policies"],
                                     "path_claims": "required"}}
    result = merge_definitions(BASELINE, mine, dict(BASELINE))

    assert result.clean
    assert result.definition["policies"]["path_claims"] == "required"
    assert "policies.path_claims" in result.kept


def test_both_sides_moving_together_is_neither_taken_nor_kept():
    changed = {**BASELINE, "schema_version": 5}
    result = merge_definitions(BASELINE, changed, dict(changed))

    assert result.clean
    assert result.definition["schema_version"] == 5
    assert "schema_version" not in result.taken + result.kept


def test_independent_changes_on_both_sides_both_survive():
    """The case the whole feature exists for."""
    mine = {**BASELINE, "policies": {**BASELINE["policies"],
                                     "path_claims": "required"}}
    theirs = {**BASELINE, "policies": {**BASELINE["policies"],
                                       "file_budget": "required"}}
    result = merge_definitions(BASELINE, mine, theirs)

    assert result.clean
    assert result.definition["policies"] == {
        "file_budget": "required", "path_claims": "required",
    }


def test_the_same_field_changed_differently_is_a_conflict_not_a_winner():
    mine = {**BASELINE, "policies": {**BASELINE["policies"],
                                     "file_budget": "required"}}
    theirs = {**BASELINE, "policies": {**BASELINE["policies"],
                                       "file_budget": "required_per_task"}}
    result = merge_definitions(BASELINE, mine, theirs)

    assert not result.clean
    conflict = result.conflicts[0]
    assert conflict.path == "policies.file_budget"
    assert (conflict.baseline, conflict.mine, conflict.theirs) == (
        "optional", "required", "required_per_task",
    )
    # The universe's value stands in the proposal until a human resolves it.
    assert result.definition["policies"]["file_budget"] == "required"


def test_a_key_yoke_added_arrives():
    theirs = {**BASELINE, "policies": {**BASELINE["policies"],
                                       "path_survey": "required"}}
    result = merge_definitions(BASELINE, dict(BASELINE), theirs)

    assert result.clean
    assert result.definition["policies"]["path_survey"] == "required"


def test_a_key_the_universe_removed_and_yoke_changed_is_a_conflict():
    mine = {**BASELINE, "policies": {"path_claims": "optional"}}
    theirs = {**BASELINE, "policies": {**BASELINE["policies"],
                                       "file_budget": "required"}}
    result = merge_definitions(BASELINE, mine, theirs)

    assert not result.clean
    assert [c.path for c in result.conflicts] == ["policies.file_budget"]


def test_a_key_yoke_removed_and_the_universe_left_alone_goes_away():
    theirs = {**BASELINE, "policies": {"path_claims": "optional"}}
    result = merge_definitions(BASELINE, dict(BASELINE), theirs)

    assert result.clean
    assert "file_budget" not in result.definition["policies"]
    assert "policies.file_budget" in result.taken


def test_without_a_baseline_every_difference_is_a_conflict():
    """An unrecorded baseline cannot tell who moved what."""
    mine = {**BASELINE, "policies": {**BASELINE["policies"],
                                     "path_claims": "required"}}
    theirs = {**BASELINE, "policies": {**BASELINE["policies"],
                                       "file_budget": "required"}}
    result = merge_definitions(None, mine, theirs)

    assert not result.clean
    assert [c.path for c in result.conflicts] == ["policies"]
    # Nothing is auto-applied; the universe's definition is returned intact.
    assert result.definition == mine


def test_the_merge_never_mutates_its_inputs():
    mine = {**BASELINE, "policies": dict(BASELINE["policies"])}
    theirs = {**BASELINE, "policies": {**BASELINE["policies"],
                                       "file_budget": "required"}}
    before = {"baseline": str(BASELINE), "mine": str(mine),
              "theirs": str(theirs)}

    merge_definitions(BASELINE, mine, theirs)

    assert str(BASELINE) == before["baseline"]
    assert str(mine) == before["mine"]
    assert str(theirs) == before["theirs"]
