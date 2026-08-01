"""Advance navigation must read an item's exact immutable workflow version."""

from __future__ import annotations

from pathlib import Path

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_PREFERRED_VERSION,
    builtin_workflow_definition,
)
from yoke_core.domain.handlers.workflows_versioning import (
    handle_workflows_item_get,
    handle_workflows_version_get,
)
from yoke_core.domain.workflow_definition_builders import workflow_stage
from yoke_core.domain.workflow_registry import publish_workflow_version


ADVANCE_SKILL = (
    Path(__file__).parents[2] / ".agents" / "skills" / "yoke" / "advance" / "SKILL.md"
)
ADVANCE_WORKFLOW_CONTEXT = ADVANCE_SKILL.with_name("workflow-context.md")


def _request(
    function: str,
    *,
    target: TargetRef,
    payload: dict | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id="advance-pin-test"),
        target=target,
        payload=payload or {},
    )


def _next_stage(definition: dict, current: str) -> str:
    stage_ids = [str(stage["id"]) for stage in definition["stages"]]
    return stage_ids[stage_ids.index(current) + 1]


def test_advance_teaches_item_pin_then_exact_version_read() -> None:
    skill = ADVANCE_SKILL.read_text()
    lookup = ADVANCE_WORKFLOW_CONTEXT.read_text()

    item_read = lookup.index("yoke workflows item get PREFIX-{N} --json")
    version_read = lookup.index(
        'yoke workflows version get "$_workflow_id" "$_workflow_version" --json'
    )

    assert item_read < version_read
    assert "[`workflow-context.md`](workflow-context.md)" in skill
    assert "yoke workflows definition get" not in lookup
    assert "current_version_id" not in lookup


def test_advance_has_no_stale_current_definition_lookup_residue() -> None:
    text = ADVANCE_SKILL.read_text() + ADVANCE_WORKFLOW_CONTEXT.read_text()

    assert "yoke workflows definition get" not in text
    assert "current_version_id" not in text
    assert "items get {N} workflow_id workflow_version_id" not in text
    assert "exact pin" in text
    assert "registry key for the exact version read" in text
    assert "no behavior branches on its value" in text


def test_existing_item_uses_pinned_definition_after_new_version_becomes_current(
    test_db,
) -> None:
    insert_item(test_db, id=943, workflow_id="issue", status="idea")

    edited_definition = builtin_workflow_definition("issue")["definition"]
    previous_stage_ids = [
        stage["id"] for stage in edited_definition["stages"]
    ]
    edited_definition["stages"].insert(
        1, workflow_stage("triaged", "Triaged"),
    )
    edited_definition["transitions"] = [
        {"from_stage_id": "idea", "to_stage_id": "triaged"},
        {"from_stage_id": "triaged", "to_stage_id": "refining-idea"},
        *edited_definition["transitions"][1:],
    ]
    edited_definition["stage_mapping"] = {
        stage_id: stage_id for stage_id in previous_stage_ids
    }
    published = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=edited_definition,
    )
    assert published["version"] == BUILTIN_WORKFLOW_PREFERRED_VERSION + 1

    pin_outcome = handle_workflows_item_get(
        _request(
            "workflows.item.get",
            target=TargetRef(kind="item", item_id=943),
        )
    )
    assert pin_outcome.primary_success
    pin = pin_outcome.result_payload
    assert pin["workflow_version"] == BUILTIN_WORKFLOW_PREFERRED_VERSION

    pinned_outcome = handle_workflows_version_get(
        _request(
            "workflows.version.get",
            target=TargetRef(kind="global"),
            payload={
                "workflow_id": pin["workflow_id"],
                "version": pin["workflow_version"],
            },
        )
    )
    current_outcome = handle_workflows_version_get(
        _request(
            "workflows.version.get",
            target=TargetRef(kind="global"),
            payload={
                "workflow_id": "issue",
                "version": published["version"],
            },
        )
    )

    assert pinned_outcome.primary_success
    assert current_outcome.primary_success
    assert pinned_outcome.result_payload["current"] is False
    assert current_outcome.result_payload["current"] is True
    assert _next_stage(pinned_outcome.result_payload["definition"], "idea") == (
        "refining-idea"
    )
    assert _next_stage(current_outcome.result_payload["definition"], "idea") == (
        "triaged"
    )
