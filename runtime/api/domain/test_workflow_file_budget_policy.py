"""Effective File Budget and path-claim policy composition."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.file_budget_required_gate import evaluate as budget_gate
from yoke_core.domain.idea_readiness_check import (
    verify_effective_file_budget_claim_consistency,
    verify_file_budget_claim_consistency,
)
from yoke_core.domain.path_claim_required_gate import evaluate as claim_gate
from yoke_core.domain.item_posture_validation import (
    ItemPostureError,
    validate_item_posture,
)
from yoke_core.domain.workflow_effective_policies import (
    load_item_effective_workflow_policies,
    resolve_effective_workflow_policies,
)
from yoke_core.domain.workflow_definition_validation import (
    WorkflowDefinitionError,
    validate_workflow_definition,
)
from yoke_core.domain.workflow_runtime import (
    builtin_workflow_runtime,
    load_item_workflow_runtime,
)
from yoke_core.domain.workflow_item_versioning import inspect_item_workflow_pin


@pytest.mark.parametrize(
    ("posture", "file_budget", "path_claims"),
    [
        ({}, "optional", "optional"),
        ({"file_budget": True}, "required", "optional"),
        ({"path_claims": True}, "optional", "required"),
        (
            {"file_budget": True, "path_claims": True},
            "required",
            "required",
        ),
    ],
)
def test_optional_axes_resolve_all_four_compositions(
    posture, file_budget, path_claims,
):
    effective = resolve_effective_workflow_policies(
        builtin_workflow_runtime("dash"),
        posture,
    )

    assert effective.file_budget == file_budget
    assert effective.path_claims == path_claims
    assert effective.requires_budget_claim_parity is (
        file_budget == path_claims == "required"
    )


def test_builtin_file_budget_defaults_match_workflow_shape():
    policies = {
        workflow_id: builtin_workflow_definition(workflow_id)[
            "definition"
        ]["policies"]
        for workflow_id in ("issue", "epic", "blitz", "dash")
    }

    assert policies["issue"]["file_budget"] == "required"
    assert policies["epic"]["file_budget"] == "required_per_task"
    assert policies["blitz"]["file_budget"] == "optional"
    assert policies["dash"]["file_budget"] == "optional"
    assert "file_budget" in policies["blitz"]["item_posture_allowlist"]
    assert "file_budget" in policies["dash"]["item_posture_allowlist"]


def test_schema_two_requires_file_budget_while_history_remains_schema_one():
    definition = deepcopy(
        builtin_workflow_definition("dash")["definition"]
    )
    definition["policies"].pop("file_budget")

    with pytest.raises(WorkflowDefinitionError, match="file_budget"):
        validate_workflow_definition(definition)


def test_file_budget_posture_only_tightens_allowlisted_optional_workflow(test_db):
    dash = builtin_workflow_definition("dash")["definition"]
    issue = builtin_workflow_definition("issue")["definition"]

    assert validate_item_posture(
        test_db,
        definition=dash,
        project_id=1,
        posture={"file_budget": True},
    ) == {"file_budget": True}
    with pytest.raises(ItemPostureError, match="must be true"):
        validate_item_posture(
            test_db,
            definition=dash,
            project_id=1,
            posture={"file_budget": False},
        )
    with pytest.raises(ItemPostureError, match="disallows"):
        validate_item_posture(
            test_db,
            definition=issue,
            project_id=1,
            posture={"file_budget": True},
        )


def test_pinned_schema_one_policy_keeps_legacy_axis_coupling(test_db):
    version_two_id = test_db.execute(
        "SELECT id FROM workflow_versions "
        "WHERE workflow_id = 'dash' AND version = 2"
    ).fetchone()[0]
    insert_item(
        test_db,
        id=3301,
        workflow_id="dash",
        workflow_posture=json.dumps({"path_claims": True}),
    )
    test_db.execute(
        "UPDATE items SET workflow_version_id = %s WHERE id = 3301",
        (version_two_id,),
    )
    test_db.commit()
    insert_item(
        test_db,
        id=3302,
        workflow_id="dash",
        workflow_posture=json.dumps({"path_claims": True}),
    )

    legacy = load_item_effective_workflow_policies(test_db, 3301)
    current = load_item_effective_workflow_policies(test_db, 3302)
    legacy_projection = inspect_item_workflow_pin(test_db, 3301)
    current_projection = inspect_item_workflow_pin(test_db, 3302)

    assert legacy.runtime.version == 2
    assert "file_budget" not in legacy.runtime.policies
    assert legacy.path_claims == legacy.file_budget == "required"
    assert current.runtime.version == 3
    assert current.path_claims == "required"
    assert current.file_budget == "optional"
    assert "file_budget" not in legacy_projection["policies"]
    assert legacy_projection["workflow_posture"] == {"path_claims": True}
    assert legacy_projection["effective_policies"]["file_budget"] == "required"
    assert legacy_projection["effective_policies"]["path_claims"] == "required"
    assert current_projection["policies"]["file_budget"] == "optional"
    assert current_projection["effective_policies"]["file_budget"] == "optional"
    assert current_projection["effective_policies"]["path_claims"] == "required"


@pytest.mark.parametrize(
    ("item_id", "posture", "budget_verdict", "claim_verdict", "parity"),
    [
        (3310, {}, "pass", "pass", False),
        (3311, {"file_budget": True}, "pass", "pass", False),
        (3312, {"path_claims": True}, "pass", "block", False),
        (
            3313,
            {"file_budget": True, "path_claims": True},
            "pass",
            "block",
            True,
        ),
    ],
)
def test_generic_gates_follow_effective_composition(
    test_db,
    item_id,
    posture,
    budget_verdict,
    claim_verdict,
    parity,
):
    insert_item(
        test_db,
        id=item_id,
        workflow_id="dash",
        workflow_posture=json.dumps(posture),
        spec="## File Budget\n\n- `src/composed.py`\n",
    )

    assert budget_gate(test_db, item_id)["verdict"] == budget_verdict
    assert claim_gate(test_db, item_id)["verdict"] == claim_verdict
    issues = verify_effective_file_budget_claim_consistency(test_db, item_id)
    assert bool(issues) is parity


def test_explicit_parity_evaluator_remains_available_when_policy_opts_out(
    test_db,
):
    insert_item(
        test_db,
        id=3319,
        workflow_id="dash",
        spec="## File Budget\n\n- `src/explicit.py`\n",
    )

    assert verify_effective_file_budget_claim_consistency(test_db, 3319) == []
    assert [
        issue.code
        for issue in verify_file_budget_claim_consistency(test_db, 3319)
    ] == ["FILE_BUDGET_NOT_IN_CLAIM"]


def test_required_file_budget_blocks_missing_section_without_claims(test_db):
    insert_item(
        test_db,
        id=3320,
        workflow_id="dash",
        workflow_posture=json.dumps({"file_budget": True}),
        spec="A small implementation instruction.",
    )

    assert budget_gate(test_db, 3320)["verdict"] == "block"
    assert claim_gate(test_db, 3320)["verdict"] == "pass"


@pytest.mark.parametrize(
    "spec",
    (
        "## File Budget\n",
        "## File Budget\n\nUNRESOLVED",
        "## File Budget\n\n- N/A — unresolved",
    ),
)
def test_required_file_budget_blocks_unresolved_content(test_db, spec):
    item_id = 3321 + len(spec)
    insert_item(
        test_db,
        id=item_id,
        workflow_id="dash",
        workflow_posture=json.dumps({"file_budget": True}),
        spec=spec,
    )

    assert budget_gate(test_db, item_id)["verdict"] == "block"


def test_required_file_budget_accepts_reasoned_no_repo_scope(test_db):
    insert_item(
        test_db,
        id=3390,
        workflow_id="dash",
        workflow_posture=json.dumps({"file_budget": True}),
        spec=(
            "## File Budget\n\n"
            "- N/A — evidence-only validation touches no repository files.\n"
        ),
    )

    assert budget_gate(test_db, 3390)["verdict"] == "pass"


def test_epic_requires_a_persisted_budget_for_each_generated_task(test_db):
    insert_item(test_db, id=3391, workflow_id="epic")
    assert budget_gate(test_db, 3391)["verdict"] == "pass"
    insert_epic_task(test_db, epic_id=3391, task_num=1)

    blocked = budget_gate(test_db, 3391)

    assert blocked["verdict"] == "block"
    assert blocked["missing_tasks"] == [1]


def test_file_line_policy_is_not_part_of_effective_workflow_policy(test_db):
    insert_item(test_db, id=3330, workflow_id="dash")
    runtime = load_item_workflow_runtime(test_db, 3330)
    effective = load_item_effective_workflow_policies(test_db, 3330)

    assert "file_line" not in runtime.policies
    assert "file_line" not in effective.values
