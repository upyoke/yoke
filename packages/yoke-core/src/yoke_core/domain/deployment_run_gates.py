"""What a deployment run is halted on, resolved for the person reading it.

A run that stops at a gate is, on the delivery surfaces, a run that simply
stops moving: the card shows a stage that never completes and gives the
reader nothing to act on. The gate itself is a ``decision_requests`` row and
already carries the answer -- which stage, what the release contains, who it
waits on -- so the card reads it from the same authority the Inbox does
rather than growing a second, thinner account of the same decision.

Two kinds reach a run. ``deployment_stage_approval`` is the pipeline
suspending on a person, keyed ``{run_id}:{stage}``. ``qa_needs_review`` is a
run-level check whose agent verdict came back undetermined, keyed by the
requirement, which reaches a run through ``qa_requirements.deployment_run_id``.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.decision_request_authority import authority_reason
from yoke_core.domain.decision_request_contract import (
    DEPLOYMENT_STAGE_APPROVAL,
    QA_NEEDS_REVIEW,
)
from yoke_core.domain.decision_requests import _request_row
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.approval_decisions import actor_decision


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _stage_approval_gates(
    conn: Any,
    run_ids: list[str],
) -> list[tuple[str, int]]:
    """Pair each run with its pending stage approvals via the subject key."""
    p = _p(conn)
    clauses = " OR ".join(f"subject_key LIKE {p}" for _ in run_ids)
    rows = conn.execute(
        "SELECT id, subject_key FROM decision_requests "
        f"WHERE kind = {p} AND subject_type = 'deployment_stage' "
        f"AND status = 'pending' AND ({clauses})",
        (DEPLOYMENT_STAGE_APPROVAL, *(f"{run_id}:%" for run_id in run_ids)),
    ).fetchall()
    return [
        (str(row["subject_key"]).rsplit(":", 1)[0], int(row["id"]))
        for row in rows
    ]


def _qa_review_gates(
    conn: Any,
    run_ids: list[str],
) -> list[tuple[str, int]]:
    """Pair each run with pending reviews of its own run-level QA checks."""
    if not _table_exists(conn, "qa_requirements"):
        return []
    p = _p(conn)
    markers = ", ".join(p for _ in run_ids)
    rows = conn.execute(
        "SELECT dr.id, qr.deployment_run_id "
        "FROM decision_requests dr "
        "JOIN qa_requirements qr "
        "ON CAST(qr.id AS TEXT) = dr.subject_key "
        f"WHERE dr.kind = {p} AND dr.subject_type = 'qa_requirement' "
        f"AND dr.status = 'pending' "
        f"AND qr.deployment_run_id IN ({markers})",
        (QA_NEEDS_REVIEW, *run_ids),
    ).fetchall()
    return [
        (str(row["deployment_run_id"]), int(row["id"])) for row in rows
    ]


def run_gates(
    conn: Any,
    run_ids: list[str],
    *,
    actor_id: Optional[int],
) -> dict[str, list[dict[str, Any]]]:
    """Return each run's pending gates, told from this reader's position.

    Every gate on the run is reported, not only the ones this reader may
    answer: a run halted on somebody else is still halted, and hiding that
    would leave the card claiming a pipeline is moving when it is not. What
    varies by reader is whether the actions are offered, which is the same
    ``authority_reason`` predicate the Inbox resolves live.
    """
    if not run_ids or not _table_exists(conn, "decision_requests"):
        return {}
    pairs = [
        *_stage_approval_gates(conn, run_ids),
        *_qa_review_gates(conn, run_ids),
    ]
    result: dict[str, list[dict[str, Any]]] = {}
    for run_id, request_id in pairs:
        request = _request_row(conn, request_id)
        reason = (
            authority_reason(conn, request_id, actor_id)
            if actor_id is not None
            else None
        )
        decision = (
            actor_decision(conn, request_id, actor_id)
            if actor_id is not None
            else None
        )
        result.setdefault(run_id, []).append(
            {
                "request_id": request_id,
                "kind": request["kind"],
                "subject_context": request["subject_context"],
                "actions": request["actions"],
                "approval_progress": request["approval_progress"],
                "requested_at": request.get("created_at"),
                "can_act": reason is not None and decision is None,
                "authority_reason": reason,
                "your_decision": decision,
                "decided_by_you": decision is not None,
            }
        )
    for gates in result.values():
        gates.sort(key=lambda gate: gate["request_id"])
    return result


__all__ = ["run_gates"]
