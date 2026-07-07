"""QA requirement creation handlers — qa.requirement.{add,add_batch}.

Item-attached requirement creation over the dispatcher, mirroring
:func:`yoke_core.domain.qa_requirements.cmd_requirement_add` /
``cmd_requirement_add_batch`` without the CLI ``sys.exit`` branches.
Validation reuses the shared domain surfaces
(:mod:`yoke_core.domain.qa_requirement_policy_validation` +
:mod:`yoke_core.domain.qa_constants` normalizers); event emission goes
through :func:`yoke_core.domain.qa_events.emit_qa_requirement_event`.

Scope: the typed surface is **item-attached only** — ``target.kind="item"``
is the claim anchor (``claim_required_kind="item"`` matches the V3 qa
write gating). Epic-task-attached and deployment-run-attached creation
keep the operator-debug domain CLI
(``python3 -m yoke_core.domain.qa requirement-add --epic-id ...``)
because the dispatcher claim matrix verifies one claim target per call.

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
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


_INSERT_SQL = (
    "INSERT INTO qa_requirements "
    "(item_id, epic_id, task_num, deployment_run_id, qa_kind, qa_phase, "
    "target_env, blocking_mode, requirement_source, success_policy, "
    "capability_requirements, suite_id, created_at) "
    "VALUES ({p}, NULL, NULL, NULL, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
    "RETURNING id"
)


class QaRequirementAddRequest(BaseModel):
    qa_kind: str
    qa_phase: str
    target_env: Optional[str] = None
    blocking_mode: str = "blocking"
    requirement_source: str = "explicit"
    success_policy: Optional[str] = None
    capability_requirements: Optional[str] = None
    suite_id: Optional[str] = None


class QaRequirementAddResponse(BaseModel):
    requirement_id: int
    item_id: int


def _validate_row(row: Dict[str, Any], jsonpath: str) -> Optional[HandlerOutcome]:
    """Shared add/add-batch row validation. Returns an error outcome or None.

    Mutates *row* in place: normalizes ``qa_kind`` / ``qa_phase`` via the
    canonical normalizers (same as the CLI path).
    """
    from yoke_core.domain.qa_constants import (
        VALID_BLOCKING_MODES,
        _normalize_qa_kind,
        _normalize_qa_phase,
    )
    from yoke_core.domain.qa_requirement_policy_validation import (
        validate_requirement_source,
        validate_success_policy,
    )

    qa_kind = row.get("qa_kind")
    qa_phase = row.get("qa_phase")
    if not isinstance(qa_kind, str) or not qa_kind:
        return _error(
            "payload_invalid", "qa_kind is required",
            jsonpath=f"{jsonpath}.qa_kind",
        )
    if not isinstance(qa_phase, str) or not qa_phase:
        return _error(
            "payload_invalid", "qa_phase is required",
            jsonpath=f"{jsonpath}.qa_phase",
        )
    row["qa_kind"] = _normalize_qa_kind(qa_kind)
    row["qa_phase"] = _normalize_qa_phase(qa_phase)

    blocking_mode = str(row.get("blocking_mode") or "blocking")
    if blocking_mode not in VALID_BLOCKING_MODES:
        return _error(
            "payload_invalid",
            "blocking_mode must be one of "
            f"{', '.join(VALID_BLOCKING_MODES)} (got {blocking_mode!r})",
            jsonpath=f"{jsonpath}.blocking_mode",
        )

    source_errors = validate_requirement_source(
        str(row.get("requirement_source") or "explicit"),
    )
    if source_errors:
        return _error(
            "payload_invalid", "; ".join(source_errors),
            jsonpath=f"{jsonpath}.requirement_source",
        )
    policy_errors = validate_success_policy(
        row["qa_kind"], row.get("success_policy"),
    )
    if policy_errors:
        return _error(
            "payload_invalid", "; ".join(policy_errors),
            jsonpath=f"{jsonpath}.success_policy",
        )
    return None


def _insert_params(item_id: int, row: Dict[str, Any], now_iso: str) -> tuple:
    return (
        int(item_id),
        row["qa_kind"],
        row["qa_phase"],
        row.get("target_env"),
        str(row.get("blocking_mode") or "blocking"),
        str(row.get("requirement_source") or "explicit"),
        row.get("success_policy"),
        row.get("capability_requirements"),
        row.get("suite_id"),
        now_iso,
    )


def handle_qa_requirement_add(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.qa_events import emit_qa_requirement_event

    item_id = request.target.item_id
    if item_id is None:
        return _error(
            "target_invalid",
            "qa.requirement.add requires target.item_id (item-attached "
            "creation; epic-task / deployment-run attachment is the "
            "operator-debug domain CLI: python3 -m yoke_core.domain.qa "
            "requirement-add)",
        )
    row = dict(request.payload or {})
    invalid = _validate_row(row, "$.payload")
    if invalid is not None:
        return invalid

    conn = connect()
    try:
        p = _p(conn)
        cur = conn.execute(
            _INSERT_SQL.format(p=p),
            _insert_params(int(item_id), row, iso8601_now()),
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
                "item_id": int(item_id), "epic_id": None,
                "task_num": None, "deployment_run_id": None,
            },
        )
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "requirement_id": inserted_id, "item_id": int(item_id),
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
            "payload_invalid", "rows must be a non-empty array",
            jsonpath="$.payload.rows",
        )

    # Pre-validate every row before opening the transaction (mirrors the
    # CLI's validate-then-insert contract).
    normalized: List[Dict[str, Any]] = []
    for idx, raw in enumerate(rows):
        jsonpath = f"$.payload.rows[{idx}]"
        if not isinstance(raw, dict):
            return _error(
                "payload_invalid", f"row {idx} is not an object",
                jsonpath=jsonpath,
            )
        row = dict(raw)
        row_item = row.get("item_id")
        if row_item is not None and int(row_item) != int(item_id):
            return _error(
                "payload_invalid",
                f"row {idx} names item_id={row_item} but the claim-verified "
                f"target is item {item_id}; one batch covers one item",
                jsonpath=f"{jsonpath}.item_id",
            )
        for foreign in ("epic_id", "task_num", "deployment_run_id"):
            if row.get(foreign) is not None:
                return _error(
                    "payload_invalid",
                    f"row {idx} sets {foreign}; the typed batch surface is "
                    "item-attached only (operator-debug domain CLI covers "
                    "other attachments)",
                    jsonpath=f"{jsonpath}.{foreign}",
                )
        invalid = _validate_row(row, jsonpath)
        if invalid is not None:
            return invalid
        normalized.append(row)

    conn = connect()
    inserted_ids: List[int] = []
    try:
        try:
            p = _p(conn)
            now_iso = iso8601_now()
            for row in normalized:
                cur = conn.execute(
                    _INSERT_SQL.format(p=p),
                    _insert_params(int(item_id), row, now_iso),
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
                    "item_id": int(item_id), "epic_id": None,
                    "task_num": None, "deployment_run_id": None,
                },
            )
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "requirement_ids": inserted_ids, "item_id": int(item_id),
        },
        primary_success=True,
    )


__all__ = [
    "QaRequirementAddRequest", "QaRequirementAddResponse",
    "handle_qa_requirement_add",
    "QaRequirementAddBatchRequest", "QaRequirementAddBatchResponse",
    "handle_qa_requirement_add_batch",
]
