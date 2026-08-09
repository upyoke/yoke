"""Preview and apply a published workflow update, preserving local edits.

Preview and apply are deliberately separate. The preview is a pure read that
shows what the merge would produce; the apply publishes it. Nothing merges and
publishes in one step, because a universe that customized its workflow deserves
to see the result before it becomes the definition new items pin.

Applying comes in one-workflow and several-workflow shapes over the same
per-workflow attempt, so a batch is exactly its entries taken individually and
reported individually -- never a looser thing that skips a guard for
convenience.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class WorkflowCanonUpdatePreviewRequest(BaseModel):
    workflow_id: str


class WorkflowCanonUpdatePreviewResponse(BaseModel):
    workflow_id: str
    state: str
    latest_canon_version: int
    derived_from_canon_version: Optional[int] = None
    clean: bool
    taken: list[str]
    kept: list[str]
    conflicts: list[Dict[str, Any]]
    definition: Dict[str, Any]


class WorkflowCanonUpdateApplyRequest(BaseModel):
    workflow_id: str
    expected_current_version: int


class WorkflowCanonUpdateApplyResponse(BaseModel):
    workflow_id: str
    version: int
    version_id: int
    definition_digest: str


class WorkflowCanonUpdateApplyAllRequest(BaseModel):
    workflows: List[WorkflowCanonUpdateApplyRequest] = Field(min_length=1)


class WorkflowCanonUpdateApplyAllResponse(BaseModel):
    applied: List[Dict[str, Any]]
    refused: List[Dict[str, Any]]


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _plan(conn: Any, workflow_id: str):
    """Resolve the three merge sides for *workflow_id* in this universe."""
    from yoke_core.domain.builtin_workflow_canon import (
        canon_generations,
        recognize,
    )
    from yoke_core.domain.workflow_canon_merge import merge_definitions
    from yoke_core.domain.workflow_registry import list_current_workflows

    workflow = next(
        (row for row in list_current_workflows(conn) if row["id"] == workflow_id),
        None,
    )
    if workflow is None:
        return None, f"unknown workflow {workflow_id!r}"
    status = workflow.get("canon_status") or {}
    if status.get("state") in (None, "not_applicable"):
        return None, f"workflow {workflow_id!r} has no published canon"
    if status["state"] == "up_to_date":
        return None, f"workflow {workflow_id!r} is already up to date"

    generations = canon_generations(workflow_id)
    theirs = generations[-1].definition
    mine = workflow["definition"]
    # The baseline is the generation this universe last agreed with: the one
    # it is running when the definition is stock, or the recorded one when it
    # has been edited. Neither is inferred from a version number.
    current = recognize(workflow_id, str(workflow["definition_digest"]))
    baseline_version = (
        current.canon_version
        if current is not None
        else status.get("derived_from_canon_version")
    )
    baseline = next(
        (
            row.definition
            for row in generations
            if row.canon_version == baseline_version
        ),
        None,
    )
    merged = merge_definitions(baseline, mine, theirs)
    return (workflow, status, generations[-1], merged), None


def _existing_version(conn: Any, workflow_id: str, definition: Any):
    """This universe's own row already holding *definition*, if it has one."""
    from yoke_core.domain.workflow_definition_codec import definition_digest
    from yoke_core.domain.workflow_registry_rows import version_row_by_digest

    return version_row_by_digest(
        conn, workflow_id, definition_digest(definition),
    )


def handle_workflows_canon_update_preview(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "workflows.canon_update.preview requires target.kind='global'",
            "$.target.kind",
        )
    try:
        payload = WorkflowCanonUpdatePreviewRequest.model_validate(
            request.payload or {}
        )
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        plan, failure = _plan(conn, payload.workflow_id)
    if plan is None:
        return _error("not_found", failure, "$.payload.workflow_id")
    _workflow, status, newest, merged = plan
    return HandlerOutcome(
        result_payload={
            "workflow_id": payload.workflow_id,
            "state": status["state"],
            "latest_canon_version": newest.canon_version,
            "derived_from_canon_version": status.get(
                "derived_from_canon_version"
            ),
            **merged.as_dict(),
        },
        primary_success=True,
    )


def _apply_one(
    conn: Any,
    entry: WorkflowCanonUpdateApplyRequest,
    actor_id: Optional[str],
) -> HandlerOutcome:
    """Take one workflow's published update, or report why it was refused.

    Returns the same outcome shape the single-workflow handler serves, so the
    batch records a refusal against the entry it belongs to without restating
    any code, message, or pointer.
    """
    from yoke_core.domain.actor_project_visibility import numeric_actor_id
    from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
    from yoke_core.domain.workflow_registry import (
        publish_workflow_version,
        set_current_workflow_version,
    )

    plan, failure = _plan(conn, entry.workflow_id)
    if plan is None:
        return _error("not_found", failure, "$.payload.workflow_id")
    _workflow, _status, _newest, merged = plan
    if not merged.clean:
        # Publishing over an unresolved conflict would silently pick a side.
        # The operator resolves it by editing, then publishes.
        return _error(
            "incompatible",
            "this update conflicts with local edits at: "
            + ", ".join(conflict.path for conflict in merged.conflicts),
            "$.payload.workflow_id",
        )
    # A universe can already hold the merged definition at an older number --
    # it rolled back, or it is taking an update that restores something it once
    # ran. Publishing would collide with the unique digest per workflow, and
    # would be wrong anyway: the row exists, so this is a selection, not a
    # publication.
    existing = _existing_version(conn, entry.workflow_id, merged.definition)
    try:
        if existing is not None:
            result = set_current_workflow_version(
                conn,
                workflow_id=entry.workflow_id,
                version=int(existing["version"]),
                expected_current_version=entry.expected_current_version,
            )
        else:
            result = publish_workflow_version(
                conn,
                workflow_id=entry.workflow_id,
                definition=merged.definition,
                published_by_actor_id=numeric_actor_id(actor_id),
                expected_current_version=entry.expected_current_version,
            )
    except WorkflowRegistryError as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_workflows_canon_update_apply(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "workflows.canon_update.apply requires target.kind='global'",
            "$.target.kind",
        )
    try:
        payload = WorkflowCanonUpdateApplyRequest.model_validate(
            request.payload or {}
        )
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        return _apply_one(conn, payload, request.actor.actor_id)


def handle_workflows_canon_update_apply_all(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Take several published updates in one operator action.

    Each workflow is attempted on its own terms and reported on its own line: a
    conflicting one refuses without holding back the rest, and the outcome names
    it rather than leaving the operator to work out which of six did not move.
    Successful entries are already committed when a later one refuses, which is
    why they are listed rather than implied.

    The caller names the workflows and the version it expects each to be on, so
    the stale-version guard that protects a single take protects every entry,
    and a batch assembled from a stale page refuses instead of overwriting what
    moved underneath it. Refusing everything is still a successful report: the
    per-entry reasons are the answer, and an error envelope would discard them.
    """
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "workflows.canon_update.apply_all requires target.kind='global'",
            "$.target.kind",
        )
    try:
        payload = WorkflowCanonUpdateApplyAllRequest.model_validate(
            request.payload or {}
        )
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    named = [entry.workflow_id for entry in payload.workflows]
    repeated = sorted({name for name in named if named.count(name) > 1})
    if repeated:
        # A workflow listed twice would race itself: the second entry carries
        # the version the first one just moved off.
        return _error(
            "payload_invalid",
            "each workflow may be named once; repeated: "
            + ", ".join(repeated),
            "$.payload.workflows",
        )
    from yoke_core.domain.db_helpers import connect

    applied: List[Dict[str, Any]] = []
    refused: List[Dict[str, Any]] = []
    with connect() as conn:
        for entry in payload.workflows:
            outcome = _apply_one(conn, entry, request.actor.actor_id)
            if outcome.primary_success:
                applied.append(outcome.result_payload)
            else:
                refused.append({
                    "workflow_id": entry.workflow_id,
                    "code": outcome.error.code,
                    "message": outcome.error.message,
                })
    return HandlerOutcome(
        result_payload={"applied": applied, "refused": refused},
        primary_success=True,
    )


__all__ = [
    "WorkflowCanonUpdateApplyAllRequest",
    "WorkflowCanonUpdateApplyAllResponse",
    "WorkflowCanonUpdateApplyRequest",
    "WorkflowCanonUpdateApplyResponse",
    "WorkflowCanonUpdatePreviewRequest",
    "WorkflowCanonUpdatePreviewResponse",
    "handle_workflows_canon_update_apply",
    "handle_workflows_canon_update_apply_all",
    "handle_workflows_canon_update_preview",
]
