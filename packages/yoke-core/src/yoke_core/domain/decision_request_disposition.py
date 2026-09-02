"""Converge pending decision requests whose subjects have already ended.

A decision request is a question put to a person about a live subject. When
that subject ends -- a QA walk is abandoned, a strategy revision is
superseded -- the question stops being answerable, but nothing about the
ending touches the request, so it stays pending forever and the Inbox fills
with blocking rows that block nothing.

This module converges them. It is deliberately kind-blind: the per-kind
subject-state contract already decides what "ended" means for each subject,
and this pass applies it to every pending row rather than teaching a second
copy of those rules.
"""

from __future__ import annotations

from typing import Any, Sequence


from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def pending_request_ids(
    conn: Any,
    *,
    project_ids: Sequence[int] | None = None,
) -> list[int]:
    """Return the pending requests this pass will evaluate."""
    if not _table_exists(conn, "decision_requests"):
        return []
    p = _p(conn)
    clause = ""
    params: tuple[Any, ...] = ()
    if project_ids is not None:
        if not project_ids:
            return []
        scopes = ", ".join([p] * len(project_ids))
        clause = f"AND (project_id IS NULL OR project_id IN ({scopes})) "
        params = tuple(int(value) for value in project_ids)
    return [
        int(row[0])
        for row in conn.execute(
            f"SELECT id FROM decision_requests WHERE status = 'pending' {clause}"
            "ORDER BY id",
            params,
        ).fetchall()
    ]


def dispose_ended_decision_requests(
    conn: Any,
    *,
    project_ids: Sequence[int] | None = None,
    session_id: str = "",
    now: Any | None = None,
) -> dict[str, Any]:
    """Reap non-progressing QA walks, then withdraw every ended-subject ask.

    Order matters: reaping settles the executions that are the reason some
    decisions can be disposed of at all, so it runs first and its own
    terminations release their decisions on the way through.
    """
    from yoke_core.domain.decision_request_resolution import (
        withdraw_for_ended_subject,
    )
    from yoke_core.domain.decision_request_subject_state import (
        require_decision_request_subject_ended,
    )
    from yoke_core.domain.decision_requests import _request_row
    from yoke_core.domain.db_helpers import iso8601_now
    from yoke_core.domain.qa_plan_execution_lifecycle import (
        reap_stale_plan_executions,
    )

    reaped = reap_stale_plan_executions(conn, now=now)
    withdrawn: list[dict[str, Any]] = []
    retained = 0
    for request_id in pending_request_ids(conn, project_ids=project_ids):
        stamp = iso8601_now()
        try:
            request = _request_row(conn, request_id)
            evidence = require_decision_request_subject_ended(
                conn, request, observed_at=stamp
            )
        except (LookupError, ValueError):
            retained += 1
            continue
        try:
            withdraw_for_ended_subject(
                conn,
                request_id,
                reason=f"subject ended: {evidence}"[:1000],
                session_id=session_id,
                withdrawn_at=stamp,
            )
        except (LookupError, ValueError):
            retained += 1
            continue
        withdrawn.append(
            {
                "request_id": request_id,
                "kind": str(request["kind"]),
                "subject_key": str(request["subject_key"]),
                "evidence": evidence,
            }
        )
    return {
        "reaped_executions": reaped,
        "withdrawn": withdrawn,
        "withdrawn_count": len(withdrawn),
        "retained_count": retained,
    }


__all__ = [
    "dispose_ended_decision_requests",
    "pending_request_ids",
]
