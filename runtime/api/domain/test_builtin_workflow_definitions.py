"""Contract tests for the first published built-in workflow definitions."""

from __future__ import annotations

from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    ENTRY_SURFACE_IDS,
    REGISTERED_WORKFLOW_EXECUTOR_IDS,
    builtin_workflow_definition,
    builtin_workflow_definitions,
)
from yoke_core.domain.workflow_gate_catalog import workflow_gate_catalog


def _stage_ids(workflow_id: str) -> tuple[str, ...]:
    fixture = builtin_workflow_definition(workflow_id)
    return tuple(
        stage["id"] for stage in fixture["definition"]["stages"]
    )


def _gate_pairs(workflow_id: str) -> set[tuple[str, str]]:
    fixture = builtin_workflow_definition(workflow_id)
    return {
        (stage["id"], gate["id"])
        for stage in fixture["definition"]["stages"]
        for gate in stage["gates"]
    }


def test_builtin_roster_and_first_versions_are_fixed():
    fixtures = builtin_workflow_definitions()
    assert tuple(row["workflow"]["id"] for row in fixtures) == (
        BUILTIN_WORKFLOW_IDS
    )
    assert {row["version"] for row in fixtures} == {1}
    assert {row["workflow"]["source"] for row in fixtures} == {"built_in"}


def test_short_workflows_make_coverage_holes_and_closures_explicit():
    blitz = _gate_pairs("blitz")
    dash = _gate_pairs("dash")

    assert not any(gate == "path_claim_boundary" for _, gate in blitz)
    assert not any(gate == "path_claim_boundary" for _, gate in dash)
    assert not any(
        stage == "refining-idea" and gate == "db_mutation"
        for stage, gate in dash
    )
    assert ("implementing", "conflict_survey") in blitz
    assert ("implementing", "conflict_survey") in dash
    assert ("done", "doc_completion") in blitz
    assert ("done", "dash_evidence") in dash


def test_definition_references_only_closed_catalog_and_registered_vocabulary():
    catalog_ids = {row["id"] for row in workflow_gate_catalog()}
    for fixture in builtin_workflow_definitions():
        definition = fixture["definition"]
        assert set(definition["entry_surfaces"]) <= ENTRY_SURFACE_IDS
        assert {
            row["executor_id"] for row in definition["executor_bindings"]
        } <= REGISTERED_WORKFLOW_EXECUTOR_IDS
        assert {
            gate["id"]
            for stage in definition["stages"]
            for gate in stage["gates"]
        } <= catalog_ids


def test_definitions_are_returned_as_caller_owned_values():
    first = builtin_workflow_definition("issue")
    first["definition"]["stages"][0]["label"] = "changed"
    second = builtin_workflow_definition("issue")
    assert second["definition"]["stages"][0]["label"] == "Idea"
