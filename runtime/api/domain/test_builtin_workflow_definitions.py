"""Contract tests for current and historical built-in workflow definitions."""

from __future__ import annotations

from copy import deepcopy

import pytest

from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_PREFERRED_VERSION,
    BUILTIN_WORKFLOW_IDS,
    ENTRY_SURFACE_IDS,
    REGISTERED_WORKFLOW_EXECUTOR_IDS,
    builtin_workflow_definition,
    builtin_workflow_definitions,
)
from yoke_core.domain.workflow_definition_validation import (
    WorkflowDefinitionError,
    validate_workflow_definition,
)
from yoke_core.domain.workflow_gate_catalog import workflow_gate_catalog

EXPECTED_WORKFLOW_COPY = {
    "dash": {
        "description": (
            "A short instruction you file in seconds — filing is the spec; "
            "an agent executes it end-to-end."
        ),
        "stages": {
            "implementing": (
                "The agent surveys for conflicts, takes a worktree, and "
                "executes the instruction in one pass."
            ),
            "reviewing-implementation": (
                "The verification close — the agent self-checks, plus any "
                "case a tightened posture knob added."
            ),
            "done": (
                "Result and verification evidence are recorded on the item; "
                "delivery, when enabled, ran as an after-merge action."
            ),
        },
    },
    "blitz": {
        "description": (
            "Execute a strategy document directly; the item is only its "
            "coordination shell. Releases happen continuously inside "
            "implementing; the close reconciles the document."
        ),
        "stages": {
            "implementing": (
                "The continuous slice loop — the linked document is executed "
                "directly, and each slice may merge, migrate, and deploy; "
                "there is no separate release stage."
            ),
            "reviewing-implementation": (
                "The once-per-item close — the full suite runs and the "
                "document records what was completed, what changed, what "
                "remains, the evidence, and how the parent strategy was "
                "reconciled."
            ),
            "done": (
                "The execution document states completion and parent "
                "reconciliation; that evidence is the entry gate."
            ),
        },
    },
    "issue": {
        "description": (
            "One scoped implementation lane with planning, review, QA and "
            "delivery."
        ),
        "stages": {
            "implementing": (
                "One implementation lane in an isolated worktree; the "
                "engineer builds against the spec and acceptance criteria."
            ),
            "reviewing-implementation": (
                "The in-worktree review loop — the work is checked against "
                "the acceptance criteria before it can leave the lane."
            ),
            "done": (
                "Merged and delivered through the selected flow; the item "
                "closes."
            ),
        },
    },
    "epic": {
        "description": (
            "Planned task decomposition with parallel worktree lanes and an "
            "integration boundary."
        ),
        "stages": {
            "planning": (
                "The Architect decomposes the epic into tasks — file budgets, "
                "interface contracts, and worktree lanes."
            ),
            "plan-drafted": (
                "The task plan is drafted and awaits the refine pass before "
                "it can be committed."
            ),
            "refining-plan": (
                "The plan is refined against the spec — simplify lenses and "
                "readiness repair — before it commits."
            ),
            "planned": (
                "The plan is committed and has passed the simulator; the "
                "tasks are ready to fan out into worktree lanes."
            ),
            "implementing": (
                "Parallel task lanes execute against the plan, each in its "
                "own worktree, with the main session integrating."
            ),
            "reviewing-implementation": (
                "Integrated task work is reviewed across the whole epic "
                "before the set can advance."
            ),
            "done": (
                "Every task merged, integrated, and delivered; the epic "
                "closes."
            ),
        },
    },
}

EXPECTED_GATE_DESCRIPTIONS = {
    "db_claim_prose": (
        "The item's declared DB claim must agree with what its own text "
        "describes — prose about migrations alongside a claim of none is "
        "refused."
    ),
    "db_mutation": (
        "A declared governed mutation must satisfy this point's check — "
        "joint: the strategy fits the project's breakage policy with no "
        "cross-item overlap; evidence: the authoritative apply evidence "
        "exists; polish: migration closeout is complete."
    ),
    "architecture_impact": (
        "The item's declared architecture impact must honor the project's "
        "authoritative architecture model (the per-project architecture_model "
        "Project Structure family)."
    ),
    "path_claim_boundary": (
        "The item's changed files must stay inside its registered path claims."
    ),
    "plan_simulation": (
        "The epic's plan must pass the simulator's cross-task execution trace."
    ),
    "qa_verification": (
        "Every QA requirement materialized for this transition must be "
        "satisfied — passed or explicitly waived."
    ),
    "check_hard_blocks": (
        "Every upstream item this one depends on must be finished before "
        "activation."
    ),
    "claim_activation": (
        "Registered path claims activate together with the worktree; a "
        "conflicting live claim refuses activation."
    ),
    "work_claim_activation": (
        "The executing session takes the exclusive work claim and a worktree."
    ),
    "doc_claim_activation": (
        "The Blitz atomically claims its single execution document; an "
        "already-owned document refuses activation."
    ),
    "conflict_survey": (
        "The agent reads claims, worktrees, and frontier items and aborts on "
        "any detected conflict."
    ),
    "doc_completion": (
        "The strategy document must record what was completed, what changed, "
        "what remains, the evidence, and the parent reconciliation."
    ),
    "dash_evidence": (
        "The result and verification evidence must be recorded on the item, "
        "plus every check the item's knobs declared — an attached plan "
        "passed, an approval resolved."
    ),
}
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
    for rows in ("transitions", "executor_bindings"):
        for row in definition[rows]:
            for key in ("from_stage_id", "to_stage_id", "through_stage_id"):
                if row.get(key) == before:
                    row[key] = after


def test_builtin_roster_and_immutable_history_are_fixed():
    fixtures = builtin_workflow_definitions()
    assert tuple(row["workflow"]["id"] for row in fixtures) == BUILTIN_WORKFLOW_IDS
    assert {row["version"] for row in fixtures} == {
        BUILTIN_WORKFLOW_PREFERRED_VERSION
    }
    assert {row["workflow"]["source"] for row in fixtures} == {"built_in"}
    assert all(
        row["definition"]["policies"]["approval_defaults"] == {}
        for row in fixtures
    )
    for row in fixtures:
        validate_workflow_definition(row["definition"])


@pytest.mark.parametrize(
    "mutate, match",
    [
        (
            lambda value: value["stages"][0]["gates"].append({"id": "unknown"}),
            "unknown gate",
        ),
        (
            lambda value: value["executor_bindings"][0].update(
                executor_id="unknown"
            ),
            "unknown executor",
        ),
        (
            lambda value: value["stages"][1].update(
                label=value["stages"][0]["label"]
            ),
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
        stage["id"]: (
            "delivering" if stage["id"] == "release" else stage["id"]
        )
        for stage in previous["stages"]
    }
    validate_workflow_definition(changed, previous=previous)


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
    catalog = {
        gate["id"]: gate["description"]
        for gate in workflow_gate_catalog()
    }
    assert {
        gate_id: catalog[gate_id]
        for gate_id in EXPECTED_GATE_DESCRIPTIONS
    } == EXPECTED_GATE_DESCRIPTIONS
