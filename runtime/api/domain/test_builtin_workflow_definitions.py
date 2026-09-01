"""Contract tests for current and historical built-in workflow definitions."""

from __future__ import annotations

from copy import deepcopy

import pytest

from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    ENTRY_SURFACE_IDS,
    REGISTERED_WORKFLOW_SKILL_IDS,
    builtin_workflow_definition,
    builtin_workflow_definitions,
    builtin_workflow_version_history,
)
from yoke_core.domain.workflow_definition_validation import (
    WorkflowDefinitionError,
    validate_workflow_definition,
)
from yoke_core.domain.workflow_gate_catalog import workflow_gate_catalog
from runtime.api.fixtures.workflow_specification_copy import (
    EXPECTED_GATE_DESCRIPTIONS,
    EXPECTED_WORKFLOW_COPY,
)


def _stage_ids(workflow_id: str) -> tuple[str, ...]:
    fixture = builtin_workflow_definition(workflow_id)
    return tuple(stage["id"] for stage in fixture["definition"]["stages"])


def _gate_pairs(workflow_id: str) -> set[tuple[str, str]]:
    fixture = builtin_workflow_definition(workflow_id)
    return {
        (stage["id"], gate["id"])
        for stage in fixture["definition"]["stages"]
        for gate in stage["gates"]
    }


def _replace_stage_id(definition: dict, before: str, after: str) -> None:
    for stage in definition["stages"]:
        if stage["id"] == before:
            stage["id"] = after
    definition["terminal_stage_ids"] = [
        after if value == before else value
        for value in definition["terminal_stage_ids"]
    ]
    for rows in ("transitions", "skill_bindings"):
        for row in definition[rows]:
            for key in ("from_stage_id", "to_stage_id", "through_stage_id"):
                if row.get(key) == before:
                    row[key] = after


def test_builtin_roster_is_fixed_and_every_current_definition_is_published():
    fixtures = builtin_workflow_definitions()
    assert tuple(row["workflow"]["id"] for row in fixtures) == BUILTIN_WORKFLOW_IDS
    # Each workflow has published a different number of times, so there is no
    # one number they share -- only the requirement that each current
    # definition be a generation the canon can recognize.
    assert all(row["canon_version"] is not None for row in fixtures)
    assert {row["workflow"]["source"] for row in fixtures} == {"built_in"}
    assert all(
        row["definition"]["policies"]["approval_defaults"] == {} for row in fixtures
    )
    for row in fixtures:
        validate_workflow_definition(row["definition"])


def test_current_stages_own_glyphs_and_history_stays_immutable():
    current = builtin_workflow_definition("dash")
    assert current["definition"]["schema_version"] == 4
    assert all(stage["glyph"] for stage in current["definition"]["stages"])
    assert all(stage["board_bucket"] for stage in current["definition"]["stages"])

    dash_history = [
        row
        for row in builtin_workflow_version_history()
        if row["workflow"]["id"] == "dash"
    ]
    # Generations are numbered from one and never renumbered, so the set is a
    # gapless run whose length is however many times dash has published.
    assert [row["canon_version"] for row in dash_history] == list(
        range(1, len(dash_history) + 1)
    )
    # Stage glyphs arrived with schema version 4. Keying on the schema version
    # rather than on a generation number is deliberate: history is not
    # monotonic in schema version, because a generation was rolled back.
    for row in dash_history:
        stages = row["definition"]["stages"]
        carries_glyphs = row["definition"]["schema_version"] >= 4
        assert all(("glyph" in stage) is carries_glyphs for stage in stages)
        assert all(("board_bucket" in stage) is carries_glyphs for stage in stages)


@pytest.mark.parametrize(
    "mutate, match",
    [
        (
            lambda value: value["stages"][0]["gates"].append({"id": "unknown"}),
            "unknown gate",
        ),
        (
            lambda value: value["skill_bindings"][0].update(skill_id="unknown"),
            "unknown skill",
        ),
        (
            lambda value: value["stages"][1].update(label=value["stages"][0]["label"]),
            "labels must be unique",
        ),
        (
            lambda value: value["policies"].update(unknown="value"),
            "keys mismatch",
        ),
    ],
)
def test_invalid_definitions_fail_closed(mutate, match):
    definition = builtin_workflow_definition("issue")["definition"]
    mutate(definition)
    with pytest.raises(WorkflowDefinitionError, match=match):
        validate_workflow_definition(definition)


def test_structural_stage_change_requires_complete_mapping():
    previous = builtin_workflow_definition("issue")["definition"]
    changed = deepcopy(previous)
    _replace_stage_id(changed, "release", "delivering")
    with pytest.raises(WorkflowDefinitionError, match="stage_mapping"):
        validate_workflow_definition(changed, previous=previous)
    changed["stage_mapping"] = {
        stage["id"]: ("delivering" if stage["id"] == "release" else stage["id"])
        for stage in previous["stages"]
    }
    validate_workflow_definition(changed, previous=previous)


def test_short_workflows_make_coverage_holes_and_closures_explicit():
    blitz = _gate_pairs("blitz")
    dash = _gate_pairs("dash")

    assert not any(gate == "path_claim_boundary" for _, gate in blitz)
    assert not any(gate == "path_claim_boundary" for _, gate in dash)
    assert not any(
        stage == "refining-idea" and gate == "db_mutation" for stage, gate in dash
    )
    assert ("implementing", "conflict_survey") in blitz
    assert ("implementing", "conflict_survey") in dash
    assert ("done", "doc_completion") in blitz
    assert ("done", "dash_evidence") in dash
    task = _gate_pairs("task")
    assert _stage_ids("task") == ("idea", "implementing", "done")
    assert ("implementing", "work_claim_activation") in task
    assert ("done", "floor_attestation") in task


def test_definition_references_only_closed_catalog_and_registered_vocabulary():
    catalog_ids = {row["id"] for row in workflow_gate_catalog()}
    for fixture in builtin_workflow_definitions():
        definition = fixture["definition"]
        assert set(definition["entry_surfaces"]) <= ENTRY_SURFACE_IDS
        assert {
            row["skill_id"] for row in definition["skill_bindings"]
        } <= REGISTERED_WORKFLOW_SKILL_IDS
        assert {
            gate["id"] for stage in definition["stages"] for gate in stage["gates"]
        } <= catalog_ids


def test_definitions_are_returned_as_caller_owned_values():
    first = builtin_workflow_definition("issue")
    first["definition"]["stages"][0]["label"] = "changed"
    second = builtin_workflow_definition("issue")
    assert second["definition"]["stages"][0]["label"] == "idea"


def test_built_in_workflow_copy_matches_the_visual_specification():
    for workflow_id, expected in EXPECTED_WORKFLOW_COPY.items():
        workflow = builtin_workflow_definition(workflow_id)
        assert workflow["workflow"]["description"] == expected["description"]
        stage_copy = {
            stage["id"]: stage["description"]
            for stage in workflow["definition"]["stages"]
            if "description" in stage
        }
        assert stage_copy == expected["stages"]


def test_gate_catalog_copy_matches_the_visual_specification():
    catalog = {gate["id"]: gate["description"] for gate in workflow_gate_catalog()}
    assert {
        gate_id: catalog[gate_id] for gate_id in EXPECTED_GATE_DESCRIPTIONS
    } == EXPECTED_GATE_DESCRIPTIONS
