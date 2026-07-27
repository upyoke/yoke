"""Immutable approval and project-owned workflow mechanic defaults."""

from __future__ import annotations

from copy import deepcopy

import pytest

from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_PREFERRED_VERSION,
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
    published = publish_workflow_policy_defaults(
        test_db,
        workflow_id="issue",
        expected_current_version=BUILTIN_WORKFLOW_PREFERRED_VERSION,
        approval_defaults={
            "done": {
                "roles": ["admin", "owner", "owner"],
                "actors": [2, 2],
            },
        },
        published_by_actor_id=2,
    )

    assert published["version"] == BUILTIN_WORKFLOW_PREFERRED_VERSION + 1
    assert published["approval_defaults"] == {
        "done": {"roles": ["owner", "admin"], "actors": [2]},
    }
    historical = get_workflow_version(
        test_db, workflow_id="issue", version=1,
    )
    current = get_workflow_version(
        test_db,
        workflow_id="issue",
        version=BUILTIN_WORKFLOW_PREFERRED_VERSION,
    )
    edited = get_workflow_version(
        test_db,
        workflow_id="issue",
        version=BUILTIN_WORKFLOW_PREFERRED_VERSION + 1,
    )
    historical_policies = historical["definition"]["policies"]
    assert "approval_defaults" not in historical_policies
    assert historical_policies.get("approval_defaults", {}) == {}
    assert current["definition"]["policies"]["approval_defaults"] == {}
    assert edited["definition"]["policies"]["approval_defaults"] == {
        "done": {"roles": ["owner", "admin"], "actors": [2]},
    }


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
            expected_current_version=BUILTIN_WORKFLOW_PREFERRED_VERSION,
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
    create_project_structure_tables(test_db)
    test_db.execute(
        "INSERT INTO deployment_flows("
        "id, project_id, name, description, stages, on_failure, created_at, "
        "status, target_env"
        ") VALUES (%s, 1, %s, '', '[]', 'halt', %s, 'active', 'production')",
        ("workflows-production", "Workflows production", "2026-07-26T00:00:00Z"),
    )
    test_db.execute(
        "INSERT INTO deployment_flows("
        "id, project_id, name, description, stages, on_failure, created_at, "
        "status, target_env"
        ") VALUES (%s, 1, %s, '', '[]', 'halt', %s, 'active', 'stage')",
        ("workflows-stage", "Workflows stage", "2026-07-26T00:00:00Z"),
    )
    test_db.commit()

    result = set_delivery_default(
        test_db,
        project="yoke",
        workflow_id="dash",
        flow_id="workflows-production",
    )

    assert result["workflow_ids"] == ["dash"]
    defaults = list_delivery_defaults(test_db)
    assert {
        (row["project"], row["workflow_id"], row["flow_id"])
        for row in defaults
    } >= {("yoke", "dash", "workflows-production")}
    assert get_workflow_version(
        test_db, workflow_id="dash", version=1,
    )["current"] is False
    assert get_workflow_version(
        test_db,
        workflow_id="dash",
        version=BUILTIN_WORKFLOW_PREFERRED_VERSION,
    )["current"] is True
    assert set_default_flow_on_connection(
        test_db, "yoke", "workflows-stage",
    ) is True
    test_db.commit()
    assert get_delivery_default(
        test_db, project="yoke", workflow_id="dash",
    ) == "workflows-production"
    assert get_delivery_default(
        test_db, project="yoke", workflow_id="issue",
    ) == "workflows-stage"
