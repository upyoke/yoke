"""Immutable approval and project-owned workflow mechanic defaults."""

from __future__ import annotations

from copy import deepcopy

import pytest

from runtime.api.workflow_version_test_helpers import current_workflow_version
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.deploy_defaults import set_default_flow_on_connection
from yoke_core.domain.project_structure import create_project_structure_tables
from yoke_core.domain.qa_plan_management import create_plan
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_definition_validation import (
    WorkflowDefinitionError,
    validate_workflow_definition,
)
from yoke_core.domain.workflow_policy_defaults import (
    publish_workflow_policy_defaults,
)
from yoke_core.domain.workflow_project_defaults import (
    get_delivery_default,
    list_delivery_defaults,
    list_testing_defaults,
    set_delivery_default,
    set_testing_default,
)
from yoke_core.domain.workflow_registry import get_workflow_version


def _definition(workflow_id: str = "issue") -> dict:
    return builtin_workflow_definition(workflow_id)["definition"]


def test_approval_defaults_are_normalized_and_publish_a_new_version(test_db):
    converged = current_workflow_version(test_db, "issue")
    published = publish_workflow_policy_defaults(
        test_db,
        workflow_id="issue",
        expected_current_version=converged,
        approval_defaults={
            "done": {
                "roles": ["admin", "owner", "owner"],
                "actors": [2, 2],
            },
        },
        published_by_actor_id=2,
    )

    assert published["version"] == converged + 1
    assert published["approval_defaults"] == {
        "done": {"roles": ["owner", "admin"], "actors": [2]},
    }
    # Publishing appends; the version that was current keeps its own content.
    before = get_workflow_version(
        test_db, workflow_id="issue", version=converged,
    )
    edited = get_workflow_version(
        test_db, workflow_id="issue", version=converged + 1,
    )
    assert before["definition"]["policies"].get("approval_defaults", {}) == {}
    assert edited["definition"]["policies"]["approval_defaults"] == {
        "done": {"roles": ["owner", "admin"], "actors": [2]},
    }


def test_file_budget_default_publishes_independently(test_db):
    converged = current_workflow_version(test_db, "dash")
    published = publish_workflow_policy_defaults(
        test_db,
        workflow_id="dash",
        expected_current_version=converged,
        file_budget_default=True,
        published_by_actor_id=2,
    )

    assert published["version"] == converged + 1
    assert published["file_budget_default"] is True
    before = get_workflow_version(
        test_db, workflow_id="dash", version=converged,
    )["definition"]["policies"]
    after = get_workflow_version(
        test_db, workflow_id="dash", version=converged + 1,
    )["definition"]["policies"]
    assert before["file_budget"] == "optional"
    assert after["file_budget"] == "required"
    assert after["path_claims"] == "optional"


def test_file_budget_default_rejects_non_allowlisted_workflow(test_db):
    with pytest.raises(WorkflowRegistryError, match="does not expose File Budget"):
        publish_workflow_policy_defaults(
            test_db,
            workflow_id="issue",
            expected_current_version=current_workflow_version(test_db, "issue"),
            file_budget_default=False,
        )


def test_approval_defaults_reject_unknown_targets_and_empty_addresses():
    unknown = deepcopy(_definition())
    unknown["policies"]["approval_defaults"] = {
        "missing": {"roles": ["owner"], "actors": []},
    }
    with pytest.raises(WorkflowDefinitionError, match="transition target"):
        validate_workflow_definition(unknown)

    empty = deepcopy(_definition())
    empty["policies"]["approval_defaults"] = {
        "done": {"roles": [], "actors": []},
    }
    with pytest.raises(WorkflowDefinitionError, match="at least one"):
        validate_workflow_definition(empty)


def test_approval_defaults_reject_unknown_named_actors(test_db):
    with pytest.raises(WorkflowRegistryError, match="does not exist"):
        publish_workflow_policy_defaults(
            test_db,
            workflow_id="issue",
            expected_current_version=current_workflow_version(test_db, "issue"),
            approval_defaults={
                "done": {"roles": [], "actors": [999999]},
            },
        )


def test_testing_default_covers_each_workflow_qa_checkpoint(test_db):
    plan = create_plan(
        test_db,
        project="yoke",
        slug="workflow-default",
        name="Workflow default",
    )
    result = set_testing_default(
        test_db,
        project="yoke",
        workflow_id="issue",
        plan_id=plan["id"],
        actor_id=2,
    )

    expected = [
        stage["id"] for stage in _definition()["stages"]
        if any(gate["id"] == "qa_verification" for gate in stage["gates"])
    ]
    assert result["transition_count"] == len(expected)
    rows = [
        row for row in list_testing_defaults(test_db)
        if row["project"] == "yoke" and row["workflow_id"] == "issue"
    ]
    assert {row["transition_id"] for row in rows} == set(expected)
    assert {row["plan_id"] for row in rows} == {plan["id"]}


def test_delivery_default_is_per_workflow_and_keeps_versions_immutable(test_db):
    converged = current_workflow_version(test_db, "dash")
    create_project_structure_tables(test_db)
    for name in ("prod", "stage"):
        test_db.execute(
            "INSERT INTO environments(site, project_id, name, created_at) "
            "SELECT id, 1, %s, %s FROM sites WHERE project_id=1 "
            "ORDER BY id LIMIT 1 ON CONFLICT(project_id,name) DO NOTHING",
            (name, "2026-07-26T00:00:00Z"),
        )
    test_db.execute(
        "INSERT INTO deployment_flows("
        "id, project_id, name, description, stages, on_failure, created_at, "
        "status, target_tier, target_environment_id"
        ") VALUES (%s, 1, %s, '', '[]', 'halt', %s, 'active', "
        "'persistent', (SELECT id FROM environments "
        "WHERE project_id=1 AND name='prod'))",
        ("workflows-prod", "Workflows prod", "2026-07-26T00:00:00Z"),
    )
    test_db.execute(
        "INSERT INTO deployment_flows("
        "id, project_id, name, description, stages, on_failure, created_at, "
        "status, target_tier, target_environment_id"
        ") VALUES (%s, 1, %s, '', '[]', 'halt', %s, 'active', "
        "'persistent', (SELECT id FROM environments "
        "WHERE project_id=1 AND name='stage'))",
        ("workflows-stage", "Workflows stage", "2026-07-26T00:00:00Z"),
    )
    test_db.commit()

    result = set_delivery_default(
        test_db,
        project="yoke",
        workflow_id="dash",
        flow_id="workflows-prod",
    )

    assert result["workflow_ids"] == ["dash"]
    defaults = list_delivery_defaults(test_db)
    assert {
        (row["project"], row["workflow_id"], row["flow_id"])
        for row in defaults
    } >= {("yoke", "dash", "workflows-prod")}
    # A delivery default is project state, not workflow content: it must not
    # publish a version, so the one that was current still is.
    assert current_workflow_version(test_db, "dash") == converged
    assert get_workflow_version(
        test_db, workflow_id="dash", version=converged,
    )["current"] is True
    assert set_default_flow_on_connection(
        test_db, "yoke", "workflows-stage",
    ) is True
    test_db.commit()
    assert get_delivery_default(
        test_db, project="yoke", workflow_id="dash",
    ) == "workflows-prod"
    assert get_delivery_default(
        test_db, project="yoke", workflow_id="issue",
    ) == "workflows-stage"
