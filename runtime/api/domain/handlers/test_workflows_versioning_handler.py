"""Handler tests for workflow pin inspection and explicit migration."""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.workflow_version_test_helpers import current_workflow_version
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.handlers.workflows_versioning import (
    handle_workflows_current_set,
    handle_workflows_item_get,
    handle_workflows_item_migrate,
    handle_workflows_policy_defaults_publish,
    handle_workflows_version_get,
)
from yoke_core.domain.handlers.workflows_version_list import (
    handle_workflows_version_list,
)
from yoke_core.domain.workflow_registry import publish_workflow_version


def _request(
    function: str,
    *,
    target: TargetRef,
    payload: dict | None = None,
    actor_id: str | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=actor_id, session_id="test-session"),
        target=target,
        payload=payload or {},
    )


def test_item_get_serves_exact_pin(test_db):
    insert_item(test_db, id=941, workflow_id="issue", status="idea")
    outcome = handle_workflows_item_get(
        _request(
            "workflows.item.get",
            target=TargetRef(kind="item", item_id=941),
        )
    )
    assert outcome.primary_success
    assert outcome.result_payload["workflow_id"] == "issue"
    assert (
        outcome.result_payload["workflow_version"]
        == current_workflow_version(test_db, "issue")
    )
    assert outcome.result_payload["status"] == "idea"


def test_current_set_changes_only_new_item_default(test_db):
    definition = builtin_workflow_definition("issue")["definition"]
    definition["stages"][0]["label"] = "Filed"
    publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=definition,
    )
    outcome = handle_workflows_current_set(
        _request(
            "workflows.current.set",
            target=TargetRef(kind="global"),
            payload={"workflow_id": "issue", "version": 1},
        )
    )
    assert outcome.primary_success
    assert outcome.result_payload["version"] == 1


def test_version_get_and_policy_default_publish(test_db):
    converged = current_workflow_version(test_db, "dash")
    version = handle_workflows_version_get(
        _request(
            "workflows.version.get",
            target=TargetRef(kind="global"),
            payload={"workflow_id": "dash", "version": converged},
        )
    )
    assert version.primary_success
    assert version.result_payload["current"] is True
    policies = version.result_payload["definition"]["policies"]
    assert policies["path_claims"] == "optional"
    assert policies.get("approval_defaults", {}) == {}

    survey = handle_workflows_policy_defaults_publish(
        _request(
            "workflows.policy_defaults.publish",
            target=TargetRef(kind="global"),
            payload={
                "workflow_id": "dash",
                "expected_current_version": converged,
                "path_survey_default": False,
            },
            actor_id="1",
        )
    )
    assert survey.primary_success

    published = handle_workflows_policy_defaults_publish(
        _request(
            "workflows.policy_defaults.publish",
            target=TargetRef(kind="global"),
            payload={
                "workflow_id": "dash",
                "expected_current_version": survey.result_payload["version"],
                "path_claims_default": True,
            },
            actor_id="1",
        )
    )
    assert published.primary_success
    assert published.result_payload["version"] == converged + 2
    assert published.result_payload["path_claims_default"] is True


def test_version_list_discovers_current_version(test_db):
    outcome = handle_workflows_version_list(
        _request(
            "workflows.version.list",
            target=TargetRef(kind="global"),
            payload={"workflow_id": "dash"},
        )
    )
    assert outcome.primary_success
    assert {row["workflow_id"] for row in outcome.result_payload["rows"]} == {"dash"}
    assert sum(row["current"] for row in outcome.result_payload["rows"]) == 1


def test_item_migrate_moves_only_compatible_target(test_db):
    converged = current_workflow_version(test_db, "issue")
    insert_item(test_db, id=942, workflow_id="issue", status="idea")
    definition = builtin_workflow_definition("issue")["definition"]
    definition["stages"][0]["label"] = "Submitted"
    publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=definition,
    )
    outcome = handle_workflows_item_migrate(
        _request(
            "workflows.item.migrate",
            target=TargetRef(kind="item", item_id=942),
        )
    )
    assert outcome.primary_success
    assert outcome.result_payload["changed"] is True
    assert (
        outcome.result_payload["after"]["workflow_version"] == converged + 1
    )


def test_versioning_handlers_validate_targets():
    outcome = handle_workflows_item_get(
        _request(
            "workflows.item.get",
            target=TargetRef(kind="global"),
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"

    outcome = handle_workflows_version_get(
        _request(
            "workflows.version.get",
            target=TargetRef(kind="item", item_id=1),
            payload={"workflow_id": "issue", "version": 1},
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"

    outcome = handle_workflows_current_set(
        _request(
            "workflows.current.set",
            target=TargetRef(kind="item", item_id=1),
            payload={"workflow_id": "issue", "version": 1},
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"
