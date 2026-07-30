"""Internal server-side item/epic reads for the done-transition engine.

The done-transition engine ran several control-plane reads by opening a
local ``connect()``, which fails over an https control plane (no local
Postgres). These handlers relay those reads server-side (dispatched
in-process against a local Postgres connection, or over https
server-side) while the engine keeps all git and filesystem work local:

* the item + pinned-workflow context load (``load_done_item_context``),
* a single stored item field read (the engine's ``_query_item_field``),
* the ``items.blocked`` refusal gate for the final done flip
  (:func:`yoke_core.domain.advance_blocked_gate.evaluate`), and
* the post-done epic-task cascade reads (the epic task list and each
  cascaded task's ``github_issue``).

Each handler is a thin wrapper over unchanged domain state — the same
query the engine ran inline, or the unchanged domain evaluator. Every
completeness/status/narrative decision stays engine-owned; these handlers
return only the raw read data. They are ``adapter_status='internal'``
(engine glue, never an agent CLI surface), so they carry no CLI adapter
inventory row.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

# The exact set of stored item fields the engine's ``_query_item_field``
# reads. Constraining the relayed field name to this set preserves the
# engine's behavior (it only ever asks for these) and keeps the read from
# becoming an arbitrary-column projection surface. ``project`` is handled
# separately because it resolves through the projects join.
_ITEM_FIELD_COLUMNS = frozenset(
    {"deployment_flow", "status", "merged_at", "deploy_stage"}
)
_PROJECT_FIELD = "project"


class ItemContextRequest(BaseModel):
    pass


class WorkflowRuntimeModel(BaseModel):
    workflow_id: str
    workflow_version_id: int
    version: int
    definition_digest: str
    definition: Dict[str, Any]


class ItemContextResponse(BaseModel):
    found: bool
    title: Optional[str] = None
    stage_id: Optional[str] = None
    lane_branch: Optional[str] = None
    project: Optional[str] = None
    workflow: Optional[WorkflowRuntimeModel] = None


class ItemFieldRequest(BaseModel):
    field: str = Field(..., min_length=1)


class ItemFieldResponse(BaseModel):
    value: str


class BlockedGateRequest(BaseModel):
    pass


class BlockedGateResponse(BaseModel):
    blocked: bool
    reason: Optional[str] = None


class EpicTaskListRequest(BaseModel):
    epic_id: str = Field(..., min_length=1)


class EpicTaskListResponse(BaseModel):
    task_list: str


class EpicTaskGithubIssuesRequest(BaseModel):
    epic_id: str = Field(..., min_length=1)
    task_nums: List[str] = Field(default_factory=list)


class EpicTaskGithubIssuesResponse(BaseModel):
    github_issues: Dict[str, str] = Field(default_factory=dict)


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _require_item_id(request: FunctionCallRequest) -> Optional[int]:
    if request.target.item_id is None:
        return None
    return int(request.target.item_id)


def handle_item_context(request: FunctionCallRequest) -> HandlerOutcome:
    """Load the item + pinned workflow context the runner consumes.

    Wraps the unchanged
    :func:`yoke_core.engines.done_transition_item_context.load_done_item_context`.
    A missing item (its ``None`` result) is a valid ``found=False`` answer,
    matching the runner's "item not found" branch; any other failure
    (including an incomplete workflow pin) surfaces as a structured error so
    the runner aborts exactly as the inline load did.
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "item_context requires target.item_id")

    from yoke_core.engines.done_transition_item_context import (
        load_done_item_context,
    )

    try:
        with _connect_rw() as conn:
            context = load_done_item_context(conn, item_id)
    except Exception as exc:  # noqa: BLE001 - surfaced so the runner aborts
        return _err("item_context_read_failed", str(exc))

    if context is None:
        return HandlerOutcome(result_payload={"found": False}, primary_success=True)

    workflow = context.workflow
    return HandlerOutcome(
        result_payload={
            "found": True,
            "title": context.title,
            "stage_id": context.stage_id,
            "lane_branch": context.lane_branch,
            "project": context.project,
            "workflow": {
                "workflow_id": workflow.workflow_id,
                "workflow_version_id": workflow.workflow_version_id,
                "version": workflow.version,
                "definition_digest": workflow.definition_digest,
                "definition": dict(workflow.definition),
            },
        },
        primary_success=True,
    )


def handle_item_field(request: FunctionCallRequest) -> HandlerOutcome:
    """Return one stored item field as the engine's ``_query_item_field`` did.

    Preserves the exact read shape: ``project`` resolves through the
    ``LEFT JOIN projects`` slug, every other allowed field reads the column
    directly, and a missing row or null value yields an empty string.
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "item_field requires target.item_id")
    try:
        body = ItemFieldRequest.model_validate(request.payload)
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"item_field payload invalid: {exc}")
    field = body.field
    if field != _PROJECT_FIELD and field not in _ITEM_FIELD_COLUMNS:
        return _err("payload_invalid", f"item_field: unsupported field {field!r}")

    try:
        with _connect_rw() as conn:
            marker = _placeholder(conn)
            if field == _PROJECT_FIELD:
                row = conn.execute(
                    "SELECT p.slug FROM items i "
                    "LEFT JOIN projects p ON p.id = i.project_id "
                    f"WHERE i.id = {marker}",
                    (item_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT {field} FROM items WHERE id = {marker}",
                    (item_id,),
                ).fetchone()
    except Exception as exc:  # noqa: BLE001 - surfaced so the caller aborts
        return _err("item_field_read_failed", str(exc))

    value = "" if row is None or row[0] is None else str(row[0])
    return HandlerOutcome(result_payload={"value": value}, primary_success=True)


def handle_blocked_gate(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the ``items.blocked`` verdict for the item id.

    Wraps :func:`yoke_core.domain.advance_blocked_gate.evaluate` unchanged so
    the same ``is_blocked`` coercion and query drive the done-flip refusal;
    the refusal narrative stays engine-owned.
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "blocked_gate requires target.item_id")

    from yoke_core.domain.advance_blocked_gate import evaluate as _eval_blocked

    try:
        with _connect_rw() as conn:
            decision = _eval_blocked(conn, item_id)
    except Exception as exc:  # noqa: BLE001 - surfaced so the caller degrades
        return _err("blocked_gate_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "blocked": bool(decision.blocked),
            "reason": decision.reason,
        },
        primary_success=True,
    )


def handle_epic_task_list(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the epic's pipe-delimited task listing for the cascade.

    Wraps :func:`yoke_core.domain.epic_resolution.task_list` unchanged; the
    engine parses the raw listing and owns the cascade/promote decisions.
    """
    try:
        body = EpicTaskListRequest.model_validate(request.payload)
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"epic_task_list payload invalid: {exc}")

    from yoke_core.domain.epic_resolution import task_list

    try:
        with _connect_rw() as conn:
            listing = task_list(conn, body.epic_id)
    except Exception as exc:  # noqa: BLE001 - surfaced so the caller aborts
        return _err("epic_task_list_failed", str(exc))

    return HandlerOutcome(
        result_payload={"task_list": listing or ""},
        primary_success=True,
    )


def handle_epic_task_github_issues(request: FunctionCallRequest) -> HandlerOutcome:
    """Return each cascaded task's ``github_issue`` in one relay.

    Runs the engine's exact per-task ``COALESCE(github_issue,'')`` query for
    every requested task number and returns a ``{task_num: github_issue}``
    map (empty string when unset/missing). Batching keeps the post-done
    GitHub sync to a single control-plane round-trip; the per-task query
    semantics are unchanged.
    """
    try:
        body = EpicTaskGithubIssuesRequest.model_validate(request.payload)
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"epic_task_github_issues invalid: {exc}")

    issues: Dict[str, str] = {}
    try:
        with _connect_rw() as conn:
            marker = _placeholder(conn)
            for task_num in body.task_nums:
                row = conn.execute(
                    "SELECT COALESCE(github_issue, '') FROM epic_tasks "
                    f"WHERE epic_id = {marker} AND task_num = {marker}",
                    (body.epic_id, task_num),
                ).fetchone()
                issues[str(task_num)] = str(row[0]) if row and row[0] else ""
    except Exception as exc:  # noqa: BLE001 - surfaced so the caller aborts
        return _err("epic_task_github_issues_failed", str(exc))

    return HandlerOutcome(
        result_payload={"github_issues": issues},
        primary_success=True,
    )


__all__ = [
    "BlockedGateRequest",
    "BlockedGateResponse",
    "EpicTaskGithubIssuesRequest",
    "EpicTaskGithubIssuesResponse",
    "EpicTaskListRequest",
    "EpicTaskListResponse",
    "ItemContextRequest",
    "ItemContextResponse",
    "ItemFieldRequest",
    "ItemFieldResponse",
    "WorkflowRuntimeModel",
    "handle_blocked_gate",
    "handle_epic_task_github_issues",
    "handle_epic_task_list",
    "handle_item_context",
    "handle_item_field",
]
