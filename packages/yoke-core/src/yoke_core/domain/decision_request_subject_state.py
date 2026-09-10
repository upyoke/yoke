"""Fail-closed subject-state checks for decision-request withdrawal."""

from __future__ import annotations

import json
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

_MACHINE_ENDED_STATES = frozenset({"expired", "withdrawn", "cancelled", "canceled"})
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
    run_text = str(_context(request).get("run_id") or "")
    if not run_text.isdigit():
        raise ValueError(f"decision request {request_id} has no verifiable QA run")
    clauses = ["verdict IN ('pass', 'fail')"]
    if _column_exists(conn, "qa_runs", "case_outcome"):
        clauses.append("case_outcome IN ('passed', 'failed')")
    conclusive = conn.execute(
        "SELECT 1 FROM qa_runs "
        f"WHERE qa_requirement_id = {_p(conn)} "
        f"AND id >= {_p(conn)} "
        f"AND ({' OR '.join(clauses)}) LIMIT 1",
        (requirement_id, int(run_text)),
    ).fetchone()
    if conclusive is not None:
        return True, f"QA requirement {requirement_id} has a conclusive result"
    return _qa_walk_ended(conn, requirement_id, int(run_text))


def _qa_review_execution_id(
    conn: Any, requirement_id: int, run_id: int
) -> str | None:
    """Resolve the one execution whose walk actually produced this run.

    Two existing durable relations carry this identity, checked in the order
    a run can appear in them: a reviewed verdict's ``review_run_id`` names
    its bundle's execution directly (``qa_plan_review_verdicts.bundle_id`` ->
    ``qa_plan_review_bundles.execution_id``); a raw capture's own advance
    embeds its run id under a runner-keyed field (``run_id`` or
    ``qa_run_id``) in that case's ``qa_plan_execution_results.result_json``.
    A run neither relation names was never durably tied to a walk.
    """
    if _table_exists(conn, "qa_plan_review_verdicts") and _table_exists(
        conn, "qa_plan_review_bundles"
    ):
        reviewed = conn.execute(
            "SELECT b.execution_id FROM qa_plan_review_verdicts v "
            "JOIN qa_plan_review_bundles b ON b.id = v.bundle_id "
            f"WHERE v.review_run_id = {_p(conn)}",
            (run_id,),
        ).fetchone()
        if reviewed is not None:
            return str(reviewed[0])
    if not _table_exists(conn, "qa_plan_execution_results"):
        return None
    for execution_id, result_json in conn.execute(
        "SELECT execution_id, result_json FROM qa_plan_execution_results "
        f"WHERE requirement_id = {_p(conn)}",
        (requirement_id,),
    ).fetchall():
        try:
            payload = json.loads(str(result_json or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, Mapping):
            continue
        for key in ("run_id", "qa_run_id"):
            value = payload.get(key)
            if value is None:
                continue
            try:
                matched = int(value) == run_id
            except (TypeError, ValueError):
                continue
            if matched:
                return str(execution_id)
    return None


def _qa_walk_ended(conn: Any, requirement_id: int, run_id: int) -> tuple[bool, str]:
    """Report whether the walk that raised this run's review was abandoned.

    A review request exists because a walk left this case undetermined. A
    walk that finished normally delivered that undetermined result on
    purpose -- the human review is the next step it is waiting on, not
    evidence the ask is moot -- so a walk completing never ends the subject
    it raised on its own. But "a walk" means the run's OWN originating
    execution, resolved through the durable relations above, never any
    other execution that happens to share the requirement: an unrelated
    execution finishing early, finishing late, or still running must not
    decide the validity of a review a different walk raised. A run no
    relation ties to any execution is a standing ad-hoc ask with no walk to
    end, so it is never disposed of this way; only independent facts
    (conclusive result, waiver, removed subject) can settle it.
    """
    if not (
        _table_exists(conn, "qa_plan_executions")
        and _table_exists(conn, "qa_plan_execution_results")
    ):
        return False, f"QA requirement {requirement_id} remains unresolved"
    execution_id = _qa_review_execution_id(conn, requirement_id, run_id)
    if execution_id is None:
        return False, (
            f"QA requirement {requirement_id} run {run_id} is not bound to a "
            "plan execution; it remains an open ask"
        )
    from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_STATES

    row = conn.execute(
        f"SELECT state FROM qa_plan_executions WHERE id = {_p(conn)}",
        (execution_id,),
    ).fetchone()
    if row is None:
        return True, f"originating execution {execution_id} no longer exists"
    state = str(row[0])
    if state in LIVE_PLAN_EXECUTION_STATES:
        return False, (
            f"QA requirement {requirement_id} is still being walked by "
            f"execution {execution_id}"
        )
    if state == "completed":
        return False, (
            f"QA requirement {requirement_id} has a plan execution that "
            f"completed normally and awaits human review ({execution_id})"
        )
    return True, (
        f"QA requirement {requirement_id}'s originating execution "
        f"{execution_id} ended as {state}"
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
