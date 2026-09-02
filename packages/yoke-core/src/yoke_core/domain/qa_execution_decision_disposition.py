"""Release the QA review decisions an ended plan execution had raised."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.decision_request_contract import QA_NEEDS_REVIEW
from yoke_core.domain.schema_common import _table_exists


WITHDRAWAL_REASON_LIMIT = 1000


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def execution_requirement_ids(execution: Mapping[str, Any]) -> list[int]:
    """Return every requirement the immutable roster asked a human about."""
    roster = execution.get("roster") or []
    return sorted(
        {
            int(case["requirement_id"])
            for case in roster
            if isinstance(case, Mapping) and case.get("requirement_id") is not None
        }
    )


def pending_review_request_ids(
    conn: Any,
    requirement_ids: Sequence[int],
) -> list[int]:
    """Return the still-open QA review decisions for those requirements."""
    if not requirement_ids or not _table_exists(conn, "decision_requests"):
        return []
    p = _p(conn)
    subjects = ", ".join([p] * len(requirement_ids))
    rows = conn.execute(
        "SELECT id FROM decision_requests WHERE status = 'pending' "
        f"AND kind = {p} AND subject_type = 'qa_requirement' "
        f"AND subject_key IN ({subjects}) ORDER BY id",
        (QA_NEEDS_REVIEW, *[str(int(value)) for value in requirement_ids]),
    ).fetchall()
    return [int(row[0]) for row in rows]


def execution_disposition_reason(execution: Mapping[str, Any]) -> str:
    """Carry the execution outcome and its operator reason onto the decision."""
    outcome = (
        f"QA plan execution {str(execution.get('id') or '<unknown>')} ended as "
        f"{str(execution.get('state') or 'unknown')}"
    )
    release_reason = str(execution.get("release_reason") or "").strip()
    reason = f"{outcome}: {release_reason}" if release_reason else outcome
    return reason[:WITHDRAWAL_REASON_LIMIT]


def dispose_execution_decisions(
    conn: Any,
    execution: Mapping[str, Any],
    *,
    session_id: str = "",
    commit: bool = True,
) -> list[dict[str, Any]]:
    """Withdraw every QA review decision this now-ended execution had raised.

    Call this only once the execution row already reads terminal, because the
    withdrawal re-verifies that fact for itself. A requirement another live
    execution is still walking is retained rather than withdrawn, and the
    retained entry names why.
    """
    from yoke_core.domain.decision_request_resolution import (
        withdraw_for_ended_subject,
    )

    reason = execution_disposition_reason(execution)
    disposed: list[dict[str, Any]] = []
    for request_id in pending_review_request_ids(
        conn, execution_requirement_ids(execution)
    ):
        try:
            withdraw_for_ended_subject(
                conn,
                request_id,
                reason=reason,
                session_id=session_id,
                commit=commit,
            )
        except ValueError as exc:
            disposed.append(
                {"request_id": request_id, "withdrawn": False, "detail": str(exc)}
            )
            continue
        disposed.append({"request_id": request_id, "withdrawn": True, "detail": reason})
    return disposed


__all__ = [
    "WITHDRAWAL_REASON_LIMIT",
    "dispose_execution_decisions",
    "execution_disposition_reason",
    "execution_requirement_ids",
    "pending_review_request_ids",
]
