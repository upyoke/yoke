"""Full-definition publication preserves immutable pins and append-only state."""

from __future__ import annotations
import pytest
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
from yoke_core.domain.workflow_registry import (
    publish_workflow_version,
    get_workflow_version,
)
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_definition_validation import WorkflowDefinitionError
from yoke_core.domain.handlers.workflows_publication import (
    handle_workflows_version_publish,
)
from runtime.api.workflow_version_test_helpers import current_workflow_version


def definition():
    value = builtin_workflow_definition("dash")["definition"]
    value["stages"][0]["label"] = "Filed locally"
    return value


def state(conn):
    return dict(conn.execute("SELECT * FROM workflows WHERE id='dash'").fetchone())


def test_append_only_preserves_current_follow_and_notice(test_db):
    before = state(test_db)
    current = current_workflow_version(test_db, "dash")
    result = publish_workflow_version(
        test_db,
        workflow_id="dash",
        definition=definition(),
        expected_current_version=current,
        keep_current=True,
        published_by_actor_id=1,
        reason="Item-specific stage level",
    )
    assert state(test_db) == before
    assert result["current"] is False
    published = get_workflow_version(
        test_db, workflow_id="dash", version=result["version"]
    )
    assert published["current"] is False
    assert published["published_by_actor_id"] == 1
    assert published["published_reason"] == "Item-specific stage level"
    changed = definition()
    changed["stages"][0]["label"] = "Next default"
    selected = publish_workflow_version(
        test_db,
        workflow_id="dash",
        definition=changed,
        expected_current_version=current,
    )
    assert selected["version"] == result["version"] + 1
    assert state(test_db)["current_version_id"] == selected["version_id"]
    assert state(test_db)["canon_follow"] == "manual"


def test_create_new_workflow_and_refuse_existing_digest(test_db):
    result = publish_workflow_version(
        test_db, workflow_id="custom", definition=definition(), reason="New workflow"
    )
    assert result["version"] == 1 and result["current"]
    assert (
        get_workflow_version(test_db, workflow_id="custom", version=1)["definition"]
        == definition()
    )
    with pytest.raises(WorkflowRegistryError, match="already published"):
        publish_workflow_version(test_db, workflow_id="custom", definition=definition())


@pytest.mark.parametrize("kind", ["stale", "invalid", "new_expected", "new_append"])
def test_refusals_leave_registry_unchanged(test_db, kind):
    before = state(test_db)
    value = definition()
    kwargs = {"workflow_id": "dash", "definition": value}
    error = WorkflowRegistryError
    if kind == "stale":
        kwargs["expected_current_version"] = (
            current_workflow_version(test_db, "dash") + 100
        )
    elif kind == "invalid":
        value["stages"] = []
        error = WorkflowDefinitionError
    elif kind == "new_expected":
        kwargs.update(workflow_id="new", expected_current_version=1)
    else:
        kwargs.update(workflow_id="new", keep_current=True)
    with pytest.raises(error):
        publish_workflow_version(test_db, **kwargs)
    assert state(test_db) == before
    assert test_db.execute("SELECT 1 FROM workflows WHERE id='new'").fetchone() is None


def test_handler_requires_expected_version_and_names_invalid_definition(test_db):
    def call(payload):
        return handle_workflows_version_publish(
            FunctionCallRequest(
                function="workflows.version.publish",
                actor=ActorContext(session_id="test-session"),
                target=TargetRef(kind="global"),
                payload=payload,
            )
        )

    payload = {
        "workflow_id": "dash",
        "definition": definition(),
        "reason": "Change levels",
    }
    result = call(payload)
    assert result.error.code == "workflow_expected_version_required"
    payload["expected_current_version"] = current_workflow_version(test_db, "dash")
    payload["definition"]["stages"] = []
    result = call(payload)
    assert result.error.code == "workflow_definition_invalid"
    assert "correct the definition" in result.error.message
