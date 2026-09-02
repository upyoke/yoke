"""Fail-closed subject-state checks for decision-request withdrawal."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.decision_request_contract import (
    DEPLOYMENT_STAGE_APPROVAL,
    LIFECYCLE_TRANSITION_APPROVAL,
    MACHINE_APPROVAL,
    QA_NEEDS_REVIEW,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists


SubjectStateCheck = Callable[
    [Any, Mapping[str, Any], str],
    tuple[bool, str],
]

_MACHINE_ENDED_STATES = frozenset(
    {"expired", "withdrawn", "cancelled", "canceled"}
)
_MACHINE_END_TIMESTAMPS = (
    "ended_at",
    "expired_at",
    "cancelled_at",
    "canceled_at",
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _context(request: Mapping[str, Any]) -> Mapping[str, Any]:
    value = request.get("subject_context")
    return value if isinstance(value, Mapping) else {}


def _require_table(conn: Any, table: str, request_id: int) -> None:
    if not _table_exists(conn, table):
        raise ValueError(
            f"decision request {request_id} subject state cannot be verified: "
            f"{table} is unavailable"
        )


def _instant(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _deployment_stage_ended(
    conn: Any,
    request: Mapping[str, Any],
    _observed_at: str,
) -> tuple[bool, str]:
    request_id = int(request["id"])
    _require_table(conn, "deployment_runs", request_id)
    context = _context(request)
    subject_parts = str(request["subject_key"]).rsplit(":", 1)
    run_id = str(context.get("run_id") or subject_parts[0]).strip()
    stage = str(
        context.get("stage") or (subject_parts[1] if len(subject_parts) == 2 else "")
    ).strip()
    if not run_id or not stage:
        raise ValueError(
            f"decision request {request_id} has no verifiable deployment stage"
        )
    row = conn.execute(
        f"SELECT status, current_stage FROM deployment_runs WHERE id = {_p(conn)}",
        (run_id,),
    ).fetchone()
    if row is None:
        return True, f"deployment run {run_id} no longer exists"
    status = str(row[0] or "")
    current_stage = str(row[1] or "")
    ended = status != "executing" or current_stage != stage
    return ended, (
        f"deployment run {run_id} is {status or 'unknown'} at "
        f"{current_stage or 'no stage'}"
    )


def _lifecycle_transition_ended(
    conn: Any,
    request: Mapping[str, Any],
    _observed_at: str,
) -> tuple[bool, str]:
    request_id = int(request["id"])
    _require_table(conn, "items", request_id)
    context = _context(request)
    item_text = str(
        context.get("item_id") or str(request["subject_key"]).split(":", 1)[0]
    )
    if not item_text.isdigit():
        raise ValueError(
            f"decision request {request_id} has no verifiable item subject"
        )
    row = conn.execute(
        "SELECT status, workflow_id, workflow_version_id FROM items "
        f"WHERE id = {_p(conn)}",
        (int(item_text),),
    ).fetchone()
    if row is None:
        return True, f"item {item_text} no longer exists"
    expected = (
        str(context.get("from_stage") or ""),
        str(context.get("workflow_id") or ""),
        int(context.get("workflow_version_id") or 0),
    )
    if not all(expected):
        raise ValueError(
            f"decision request {request_id} has no verifiable transition snapshot"
        )
    current = (str(row[0]), str(row[1]), int(row[2]))
    ended = current != expected or request.get("consumed_at") is not None
    return ended, (
        f"item {item_text} snapshot is {current[0]} on {current[1]}@{current[2]}"
    )


def _qa_review_ended(
    conn: Any,
    request: Mapping[str, Any],
    _observed_at: str,
) -> tuple[bool, str]:
    request_id = int(request["id"])
    _require_table(conn, "qa_requirements", request_id)
    requirement_text = str(
        _context(request).get("requirement_id") or request["subject_key"]
    )
    if not requirement_text.isdigit():
        raise ValueError(
            f"decision request {request_id} has no verifiable QA requirement"
        )
    requirement_id = int(requirement_text)
    requirement = conn.execute(
        f"SELECT waived_at FROM qa_requirements WHERE id = {_p(conn)}",
        (requirement_id,),
    ).fetchone()
    if requirement is None:
        return True, f"QA requirement {requirement_id} no longer exists"
    if requirement[0] is not None:
        return True, f"QA requirement {requirement_id} was waived"
    if not _table_exists(conn, "qa_runs"):
        return False, f"QA requirement {requirement_id} remains unresolved"
    clauses = ["verdict IN ('pass', 'fail')"]
    if _column_exists(conn, "qa_runs", "case_outcome"):
        clauses.append("case_outcome IN ('passed', 'failed')")
    conclusive = conn.execute(
        "SELECT 1 FROM qa_runs "
        f"WHERE qa_requirement_id = {_p(conn)} "
        f"AND ({' OR '.join(clauses)}) LIMIT 1",
        (requirement_id,),
    ).fetchone()
    if conclusive is not None:
        return True, f"QA requirement {requirement_id} has a conclusive result"
    return _qa_walk_ended(conn, requirement_id)


def _qa_walk_ended(conn: Any, requirement_id: int) -> tuple[bool, str]:
    """Report whether every plan execution that walked this case has ended.

    A review request exists because a walk could not determine a verdict. Once
    every execution that walked the case is terminal, no further evidence is
    coming and the ask is over -- the requirement itself stays unresolved, and
    that is the answer. A requirement no execution ever walked is a standing
    ad-hoc ask with no walk to end, so it is never disposed of this way.
    """
    if not (
        _table_exists(conn, "qa_plan_executions")
        and _table_exists(conn, "qa_plan_execution_results")
    ):
        return False, f"QA requirement {requirement_id} remains unresolved"
    from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_STATES

    walks = conn.execute(
        "SELECT e.id, e.state FROM qa_plan_execution_results r "
        "JOIN qa_plan_executions e ON e.id = r.execution_id "
        f"WHERE r.requirement_id = {_p(conn)} ORDER BY e.created_at, e.id",
        (requirement_id,),
    ).fetchall()
    if not walks:
        return False, (
            f"QA requirement {requirement_id} has no plan execution to end; "
            "it remains an open ask"
        )
    live = [str(row[0]) for row in walks if str(row[1]) in LIVE_PLAN_EXECUTION_STATES]
    if live:
        return False, (
            f"QA requirement {requirement_id} is still being walked by "
            f"execution {live[0]}"
        )
    outcomes = ", ".join(f"{row[0]} {row[1]}" for row in walks)
    return True, (
        f"QA requirement {requirement_id} has no live plan execution left "
        f"({outcomes})"
    )



def _machine_approval_ended(
    _conn: Any,
    request: Mapping[str, Any],
    observed_at: str,
) -> tuple[bool, str]:
    request_id = int(request["id"])
    context = _context(request)
    state = str(context.get("status") or context.get("state") or "").lower()
    if state in _MACHINE_ENDED_STATES:
        return True, f"machine authorization is {state}"
    observed = _instant(observed_at)
    if observed is None:
        raise ValueError(
            f"decision request {request_id} has an invalid observation timestamp"
        )
    for key in _MACHINE_END_TIMESTAMPS:
        if context.get(key) is None:
            continue
        instant = _instant(context[key])
        if instant is None:
            raise ValueError(
                f"decision request {request_id} has invalid {key} evidence"
            )
        if instant <= observed:
            return True, f"machine authorization reached {key} at {context[key]}"
    expires_at = _instant(context.get("expires_at"))
    if expires_at is not None and expires_at <= observed:
        return True, (f"machine authorization expired at {context['expires_at']}")
    return False, "machine authorization has not expired or been cancelled"


_SUBJECT_STATE_CHECKS: dict[str, SubjectStateCheck] = {
    DEPLOYMENT_STAGE_APPROVAL: _deployment_stage_ended,
    QA_NEEDS_REVIEW: _qa_review_ended,
    LIFECYCLE_TRANSITION_APPROVAL: _lifecycle_transition_ended,
    MACHINE_APPROVAL: _machine_approval_ended,
}


def require_decision_request_subject_ended(
    conn: Any,
    request: Mapping[str, Any],
    *,
    observed_at: str,
) -> str:
    """Return audited end evidence or reject an active/unverifiable subject."""
    request_id = int(request["id"])
    checker = _SUBJECT_STATE_CHECKS.get(str(request["kind"]))
    if checker is None:
        raise ValueError(f"decision request {request_id} has no subject-state contract")
    ended, evidence = checker(conn, request, observed_at)
    if not ended:
        raise ValueError(
            f"decision request {request_id} subject has not ended: {evidence}"
        )
    return evidence


__all__ = ["require_decision_request_subject_ended"]
