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
    STRATEGY_REVISION_REVIEW,
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
    return conclusive is not None, (
        f"QA requirement {requirement_id} "
        f"{'has a conclusive result' if conclusive else 'remains unresolved'}"
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


def _strategy_revision_ended(
    conn: Any,
    request: Mapping[str, Any],
    _observed_at: str,
) -> tuple[bool, str]:
    request_id = int(request["id"])
    _require_table(conn, "strategy_docs", request_id)
    _require_table(conn, "strategy_doc_revisions", request_id)
    context = _context(request)
    parts = str(request["subject_key"]).split(":")
    project_id = int(context.get("project_id") or request.get("project_id") or 0)
    slug = str(context.get("slug") or ":".join(parts[1:-1])).strip()
    revision = int(context.get("revision") or (parts[-1] if parts else 0))
    if not project_id or not slug or not revision:
        raise ValueError(
            f"decision request {request_id} has no verifiable strategy revision"
        )
    p = _p(conn)
    revision_row = conn.execute(
        "SELECT 1 FROM strategy_doc_revisions "
        f"WHERE project_id = {p} AND slug = {p} AND revision = {p}",
        (project_id, slug, revision),
    ).fetchone()
    if revision_row is None:
        return True, f"strategy revision {slug}@{revision} no longer exists"
    archived_select = (
        "archived_at"
        if _column_exists(conn, "strategy_docs", "archived_at")
        else "NULL"
    )
    doc = conn.execute(
        f"SELECT {archived_select} FROM strategy_docs "
        f"WHERE project_id = {p} AND slug = {p}",
        (project_id, slug),
    ).fetchone()
    if doc is None:
        return True, f"strategy document {slug} no longer exists"
    if doc[0] is not None:
        return True, f"strategy document {slug} is archived"
    latest = conn.execute(
        "SELECT MAX(revision) FROM strategy_doc_revisions "
        f"WHERE project_id = {p} AND slug = {p}",
        (project_id, slug),
    ).fetchone()
    latest_revision = int(latest[0] or 0)
    return latest_revision > revision, (
        f"strategy revision {slug}@{revision} "
        f"{'was superseded' if latest_revision > revision else 'remains current'}"
    )


_SUBJECT_STATE_CHECKS: dict[str, SubjectStateCheck] = {
    DEPLOYMENT_STAGE_APPROVAL: _deployment_stage_ended,
    QA_NEEDS_REVIEW: _qa_review_ended,
    LIFECYCLE_TRANSITION_APPROVAL: _lifecycle_transition_ended,
    MACHINE_APPROVAL: _machine_approval_ended,
    STRATEGY_REVISION_REVIEW: _strategy_revision_ended,
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
