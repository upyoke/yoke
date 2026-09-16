"""QA requirement creation handlers — qa.requirement.{add,add_batch}.

Item-attached requirement creation over the dispatcher, mirroring
:func:`yoke_core.domain.qa_requirements.cmd_requirement_add` /
``cmd_requirement_add_batch`` without the CLI ``sys.exit`` branches.
Validation reuses the shared domain surfaces
(:mod:`yoke_core.domain.qa_requirement_policy_validation` +
:mod:`yoke_core.domain.qa_constants` normalizers); event emission goes
through :func:`yoke_core.domain.qa_events.emit_qa_requirement_event`.

Scope: ``add`` serves two attachment shapes through one function id and
one claim policy. ``target.kind="item"`` anchors an item case on the
session's live item claim; ``target.kind="deployment_run"`` anchors a
run case on that run's own project scope, which is the same
``claim_required_kind="qa_subject"`` policy every other QA write already
uses — the run-attached half lives in
:mod:`yoke_core.domain.handlers.qa_requirement_deployment_run_create`.
Epic-task attachment keeps the operator-debug domain CLI
(``python3 -m yoke_core.domain.qa requirement-add --epic-id ...
--workflow-transition STAGE``).

``add_batch`` accepts rows for the TARGET item only: rows may omit
``item_id`` (defaulted from the target) and any row naming a different
attachment is rejected before the transaction opens. The whole batch
inserts in one transaction; per-row ``QARequirementCreated`` events emit
after commit (mirrors the CLI contract).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_core.domain.handlers.qa import _error, _p
from yoke_core.domain.handlers.qa_requirement_deployment_run_create import (
    handle_deployment_run_requirement_add,
)
from yoke_core.domain.handlers.qa_requirement_insert import (
    INSERT_SQL,
    RequirementSubject,
    insert_params,
)
from yoke_core.domain.handlers.qa_requirement_row_validation import validate_row
from yoke_core.domain.handlers.qa_requirement_method_validation import (
    validate_method_requirement,
)
from yoke_core.domain.handlers.qa_requirement_transition_validation import (
    validate_workflow_transition,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)
from yoke_core.domain.project_identity_item_ref import item_ref_for_id


class QaRequirementAddRequest(BaseModel):
    qa_kind: Optional[str] = None
    qa_phase: str
    target_env: Optional[str] = None
    blocking_mode: str = "blocking"
    requirement_source: str = "explicit"
    success_policy: Optional[str] = None
    capability_requirements: Optional[List[str]] = None
    suite_id: Optional[str] = None
    method_id: Optional[str] = None
    instructions: Optional[str] = None
    expected_outcome: Optional[str] = None
    method_config: Optional[Dict[str, Any]] = None
    #: An item-attached case names the pinned workflow stage it governs. A
    #: run-attached one is governed by its deployment run instead, so the
    #: field is absent there rather than filled with a stage it does not
    #: answer to.
    workflow_transition_id: Optional[str] = None
    #: Run-attached only: which stage of the run the case is about, and
    #: which member item within that stage — named as the run carries it,
    #: by public ref or item id. Both are refused on an item-attached call,
    #: whose subject is the item itself.
    deployment_stage: Optional[str] = None
    deployment_member_item: Optional[str] = None


class QaRequirementAddResponse(BaseModel):
    requirement_id: int
    #: The subject the new case is attached to: an item, or a deployment run
    #: and optionally one stage and member inside it. Exactly one of the two
    #: identities is populated, matching the row that was written.
    item_id: Optional[int] = None
    deployment_run_id: Optional[str] = None
    deployment_stage: Optional[str] = None
    deployment_member_item_id: Optional[int] = None


def handle_qa_requirement_add(request: FunctionCallRequest) -> HandlerOutcome:
    """Create one case against whichever subject the target names."""
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.qa_events import emit_qa_requirement_event

    if request.target.kind == "deployment_run":
        return handle_deployment_run_requirement_add(request)
    item_id = request.target.item_id
    if item_id is None:
        return _error(
            "target_invalid",
            "qa.requirement.add requires target.item_id for an item-attached "
            "case, or target.kind='deployment_run' with "
            "target.deployment_run_id for a run-attached one (epic-task "
            "attachment is the operator-debug domain CLI: python3 -m "
            "yoke_core.domain.qa requirement-add)",
        )
    row = dict(request.payload or {})
    for run_only in ("deployment_stage", "deployment_member_item"):
        if row.get(run_only) is not None:
            return _error(
                "payload_invalid",
                f"{run_only} describes a deployment run's own case; an "
                "item-attached case is subject to its item. Target the run "
                "with target.kind='deployment_run' instead.",
                jsonpath=f"$.payload.{run_only}",
            )
        row.pop(run_only, None)
    invalid = validate_row(row, "$.payload")
    if invalid is not None:
        return invalid

    conn = connect()
    try:
        lock_item_workflow_bindings(conn, (int(item_id),))
        invalid = validate_method_requirement(conn, row, "$.payload")
        if invalid is not None:
            return invalid
        invalid = validate_workflow_transition(
            conn,
            item_id=int(item_id),
            row=row,
            jsonpath="$.payload",
        )
        if invalid is not None:
            return invalid
        p = _p(conn)
        cur = conn.execute(
            INSERT_SQL.format(p=p),
            insert_params(RequirementSubject.for_item(item_id), row, iso8601_now()),
        )
        inserted_id = int(cur.fetchone()[0])
        conn.commit()
        emit_qa_requirement_event(
            conn,
            db_path=None,
            event_name="QARequirementCreated",
            requirement_id=inserted_id,
            qa_kind=row["qa_kind"],
            qa_phase=row["qa_phase"],
            target_row={
                "item_id": int(item_id),
                "epic_id": None,
                "task_num": None,
                "deployment_run_id": None,
            },
        )
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "requirement_id": inserted_id,
            "item_id": int(item_id),
        },
        primary_success=True,
    )


class QaRequirementAddBatchRequest(BaseModel):
    rows: List[Dict[str, Any]]


class QaRequirementAddBatchResponse(BaseModel):
    requirement_ids: List[int]
    item_id: int


def handle_qa_requirement_add_batch(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.qa_events import emit_qa_requirement_event

    item_id = request.target.item_id
    if item_id is None:
        return _error(
            "target_invalid",
            "qa.requirement.add_batch requires target.item_id",
        )
    payload = request.payload or {}
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return _error(
            "payload_invalid",
            "rows must be a non-empty array",
            jsonpath="$.payload.rows",
        )

    # Pre-validate every row before opening the transaction (mirrors the
    # CLI's validate-then-insert contract).
    normalized: List[Dict[str, Any]] = []
    for idx, raw in enumerate(rows):
        jsonpath = f"$.payload.rows[{idx}]"
        if not isinstance(raw, dict):
            return _error(
                "payload_invalid",
                f"row {idx} is not an object",
                jsonpath=jsonpath,
            )
        row = dict(raw)
        row_item = row.get("item_id")
        if row_item is not None and int(row_item) != int(item_id):
            return _error(
                "payload_invalid",
                f"row {idx} names item_id={row_item} but the claim-verified "
                f"target is {item_ref_for_id(item_id)}; one batch covers one item",
                jsonpath=f"{jsonpath}.item_id",
            )
        for foreign in ("epic_id", "task_num", "deployment_run_id"):
            if row.get(foreign) is not None:
                return _error(
                    "payload_invalid",
                    f"row {idx} sets {foreign}; the batch surface is "
                    "item-attached only. Author a run case one at a time "
                    "with target.kind='deployment_run'.",
                    jsonpath=f"{jsonpath}.{foreign}",
                )
        invalid = validate_row(row, jsonpath)
        if invalid is not None:
            return invalid
        normalized.append(row)

    conn = connect()
    inserted_ids: List[int] = []
    try:
        try:
            lock_item_workflow_bindings(conn, (int(item_id),))
            p = _p(conn)
            now_iso = iso8601_now()
            for row in normalized:
                invalid = validate_method_requirement(
                    conn,
                    row,
                    f"$.payload.rows[{len(inserted_ids)}]",
                )
                if invalid is not None:
                    conn.rollback()
                    return invalid
                invalid = validate_workflow_transition(
                    conn,
                    item_id=int(item_id),
                    row=row,
                    jsonpath=f"$.payload.rows[{len(inserted_ids)}]",
                )
                if invalid is not None:
                    conn.rollback()
                    return invalid
                cur = conn.execute(
                    INSERT_SQL.format(p=p),
                    insert_params(RequirementSubject.for_item(item_id), row, now_iso),
                )
                inserted_ids.append(int(cur.fetchone()[0]))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        for i, row in enumerate(normalized):
            emit_qa_requirement_event(
                conn,
                db_path=None,
                event_name="QARequirementCreated",
                requirement_id=inserted_ids[i],
                qa_kind=row["qa_kind"],
                qa_phase=row["qa_phase"],
                target_row={
                    "item_id": int(item_id),
                    "epic_id": None,
                    "task_num": None,
                    "deployment_run_id": None,
                },
            )
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "requirement_ids": inserted_ids,
            "item_id": int(item_id),
        },
        primary_success=True,
    )


__all__ = [
    "QaRequirementAddRequest",
    "QaRequirementAddResponse",
    "handle_qa_requirement_add",
    "QaRequirementAddBatchRequest",
    "QaRequirementAddBatchResponse",
    "handle_qa_requirement_add_batch",
]
