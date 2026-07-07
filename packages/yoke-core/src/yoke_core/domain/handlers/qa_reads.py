"""QA read handlers — qa.requirement.{list,get}, qa.run.{list,get},
qa.gate_summary.run.

Typed read legs for the ``qa`` family (family docstring:
:mod:`yoke_core.domain.handlers.qa_browser`). Each handler wraps the
matching db_router/domain read without the CLI ``print``/``sys.exit``
presentation:

- ``qa.requirement.list`` — mirrors
  :func:`yoke_core.domain.qa_requirement_ops.cmd_requirement_list`
  (item / epic / deployment-run filter precedence) returning structured
  rows over :data:`yoke_core.domain.qa_constants.REQ_COLUMNS`.
- ``qa.requirement.get`` — mirrors ``cmd_requirement_get`` for one
  ``qa_requirements`` row.
- ``qa.run.list`` — mirrors
  :func:`yoke_core.domain.qa_execution.cmd_run_list` over
  :data:`yoke_core.domain.qa_constants.RUN_COLUMNS` (typed superset:
  includes ``execution_status``).
- ``qa.run.get`` — returns one ``qa_runs`` row by id over the same
  structured column set.
- ``qa.gate_summary.run`` — calls
  :func:`yoke_core.domain.qa_gate_summary.render_gate_summary`
  directly (pure read, no CLI branches to strip). This is the
  dispatcher-backed fix for the checkout-shaped gate-entry leg that
  could not run over https.

All four are reads: ``claim_required_kind=None``, no side effects, only
``YokeFunctionCalled`` emission.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_core.domain.handlers.qa import _error, _p
from yoke_core.domain.qa_constants import REQ_COLUMNS, RUN_COLUMNS
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


def _rows_to_dicts(rows: Any, columns: tuple) -> List[Dict[str, Any]]:
    return [{col: row[col] for col in columns} for row in rows]


# ---------------------------------------------------------------------------
# qa.requirement.list
# ---------------------------------------------------------------------------


class QaRequirementListRequest(BaseModel):
    item_id: Optional[int] = None
    epic_id: Optional[int] = None
    deployment_run_id: Optional[str] = None


class QaRequirementListResponse(BaseModel):
    rows: List[Dict[str, Any]]


def handle_qa_requirement_list(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_rows

    payload = request.payload or {}
    item_id = payload.get("item_id")
    if (
        item_id is None
        and request.target.kind == "item"
        and request.target.item_id is not None
    ):
        # Relay shape: the --item filter rides the envelope target as a
        # raw ref; the dispatcher resolved it into target.item_id.
        item_id = int(request.target.item_id)
    epic_id = payload.get("epic_id")
    deployment_run_id = payload.get("deployment_run_id")

    # Filter precedence mirrors cmd_requirement_list: item, then epic,
    # then deployment run; no filter lists every row.
    where = "1=1"
    params: tuple = ()
    if item_id is not None:
        where, params = "item_id = {p}", (int(item_id),)
    elif epic_id is not None:
        where, params = "epic_id = {p}", (int(epic_id),)
    elif deployment_run_id is not None:
        where, params = "deployment_run_id = {p}", (str(deployment_run_id),)

    conn = connect()
    try:
        rows = query_rows(
            conn,
            f"SELECT {', '.join(REQ_COLUMNS)} FROM qa_requirements "
            f"WHERE {where.format(p=_p(conn))} ORDER BY id",
            params,
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"rows": _rows_to_dicts(rows, REQ_COLUMNS)},
        primary_success=True,
    )


# ---------------------------------------------------------------------------
# qa.requirement.get
# ---------------------------------------------------------------------------


class QaRequirementGetRequest(BaseModel):
    pass


class QaRequirementGetResponse(BaseModel):
    requirement: Dict[str, Any]


def handle_qa_requirement_get(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_one

    req_id = request.target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.requirement.get requires target.qa_requirement_id",
        )
    conn = connect()
    try:
        row = query_one(
            conn,
            f"SELECT {', '.join(REQ_COLUMNS)} FROM qa_requirements "
            f"WHERE id = {_p(conn)}",
            (int(req_id),),
        )
    finally:
        conn.close()
    if row is None:
        return _error("not_found", f"requirement {req_id} not found")
    return HandlerOutcome(
        result_payload={
            "requirement": {col: row[col] for col in REQ_COLUMNS},
        },
        primary_success=True,
    )


# ---------------------------------------------------------------------------
# qa.run.list / qa.run.get
# ---------------------------------------------------------------------------


class QaRunListRequest(BaseModel):
    requirement_id: Optional[int] = None


class QaRunListResponse(BaseModel):
    rows: List[Dict[str, Any]]


class QaRunGetRequest(BaseModel):
    run_id: int


class QaRunGetResponse(BaseModel):
    run: Dict[str, Any]


def handle_qa_run_list(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_rows

    payload = request.payload or {}
    requirement_id = payload.get("requirement_id")
    if requirement_id is None and request.target.qa_requirement_id is not None:
        requirement_id = int(request.target.qa_requirement_id)

    where = "1=1"
    params: tuple = ()
    if requirement_id is not None:
        where, params = "qa_requirement_id = {p}", (int(requirement_id),)

    conn = connect()
    try:
        rows = query_rows(
            conn,
            f"SELECT {', '.join(RUN_COLUMNS)} FROM qa_runs "
            f"WHERE {where.format(p=_p(conn))} ORDER BY id",
            params,
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"rows": _rows_to_dicts(rows, RUN_COLUMNS)},
        primary_success=True,
    )


def handle_qa_run_get(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_one

    payload = request.payload or {}
    run_id = payload.get("run_id")
    if not isinstance(run_id, int):
        return _error(
            "payload_invalid", "run_id is required",
            jsonpath="$.payload.run_id",
        )

    conn = connect()
    try:
        row = query_one(
            conn,
            f"SELECT {', '.join(RUN_COLUMNS)} FROM qa_runs "
            f"WHERE id = {_p(conn)}",
            (int(run_id),),
        )
    finally:
        conn.close()
    if row is None:
        return _error("not_found", f"run {run_id} not found")
    return HandlerOutcome(
        result_payload={"run": {col: row[col] for col in RUN_COLUMNS}},
        primary_success=True,
    )


# ---------------------------------------------------------------------------
# qa.gate_summary.run
# ---------------------------------------------------------------------------


class QaGateSummaryRequest(BaseModel):
    transition: str


class QaGateSummaryResponse(BaseModel):
    target: str
    transition: str
    qa_tables_present: bool
    no_requirements: bool
    satisfied: bool
    blocking_unsatisfied_count: int
    browser_unsatisfied_count: int
    e2e_unsatisfied_count: int
    requirements: List[Dict[str, Any]]


def handle_qa_gate_summary(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.qa_gate_definitions import GateTarget
    from yoke_core.domain.qa_gate_summary import (
        VALID_TARGETS,
        render_gate_summary,
    )

    target = request.target
    if target.kind == "item" and target.item_id is not None:
        gate_target = GateTarget(item_id=int(target.item_id))
    elif (
        target.kind == "epic_task"
        and target.epic_id is not None
        and target.task_num is not None
    ):
        gate_target = GateTarget(
            epic_id=int(target.epic_id), task_num=int(target.task_num),
        )
    else:
        return _error(
            "target_invalid",
            "qa.gate_summary.run requires target.item_id OR "
            "target.epic_id + target.task_num",
        )

    payload = request.payload or {}
    transition = payload.get("transition")
    if transition not in VALID_TARGETS:
        return _error(
            "payload_invalid",
            f"transition must be one of {list(VALID_TARGETS)}",
            jsonpath="$.payload.transition",
        )

    # db_path=None selects the canonical Postgres authority, exactly like
    # every other handler's bare connect().
    summary = render_gate_summary(
        gate_target, None, transition_name=str(transition),
    )
    return HandlerOutcome(result_payload=summary, primary_success=True)


__all__ = [
    "QaRequirementListRequest", "QaRequirementListResponse",
    "handle_qa_requirement_list",
    "QaRequirementGetRequest", "QaRequirementGetResponse",
    "handle_qa_requirement_get",
    "QaRunListRequest", "QaRunListResponse", "handle_qa_run_list",
    "QaRunGetRequest", "QaRunGetResponse", "handle_qa_run_get",
    "QaGateSummaryRequest", "QaGateSummaryResponse",
    "handle_qa_gate_summary",
]
