"""What a deployment run is halted on, resolved for the person reading it.

A run that stops at a gate is, on the delivery surfaces, a run that simply
stops moving: the card shows a stage that never completes and gives the
reader nothing to act on. The gate itself is a ``decision_requests`` row and
already carries the answer -- which stage, what the release contains, who it
waits on -- so the card reads it from the same authority the Inbox does
rather than growing a second, thinner account of the same decision.

Three kinds reach a run. ``deployment_stage_approval`` carries both a pending
action and its resolved human decision, keyed ``{run_id}:{stage}``.
``qa_needs_review`` carries pending and resolved human reviews of run-level
and member QA evidence, reaching the run through
``qa_requirements.deployment_run_id``.
``lifecycle_transition_approval`` belongs to a carried final member and
keeps that item's own project approval authority.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.timestamps import temporal_wire
from yoke_core.domain import db_backend
from yoke_core.domain.decision_request_contract import (
    DEPLOYMENT_STAGE_APPROVAL,
    LIFECYCLE_TRANSITION_APPROVAL,
    QA_NEEDS_REVIEW,
)
from yoke_core.domain.decision_gate_record import gate_record
from yoke_core.domain.decision_requests import _request_row
from yoke_core.domain.deployment_run_project_presentation import (
    project_visible,
    visible_carried_work,
)
from yoke_core.domain.schema_common import _table_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _stage_approval_gates(
    conn: Any,
    run_ids: list[str],
) -> list[tuple[str, int]]:
    """Pair each run with pending and resolved stage approvals."""
    p = _p(conn)
    clauses = " OR ".join(f"subject_key LIKE {p}" for _ in run_ids)
    rows = conn.execute(
        "SELECT id, subject_key FROM decision_requests "
        f"WHERE kind = {p} AND subject_type = 'deployment_stage' "
        f"AND status IN ('pending', 'resolved') AND ({clauses})",
        (DEPLOYMENT_STAGE_APPROVAL, *(f"{run_id}:%" for run_id in run_ids)),
    ).fetchall()
    return [(str(row["subject_key"]).rsplit(":", 1)[0], int(row["id"])) for row in rows]


def _qa_review_gates(
    conn: Any,
    run_ids: list[str],
    visible_project_ids: set[int] | None,
) -> list[tuple[str, int]]:
    """Pair each run with pending and resolved reviews of its QA checks."""
    if not _table_exists(conn, "qa_requirements"):
        return []
    p = _p(conn)
    markers = ", ".join(p for _ in run_ids)
    rows = conn.execute(
        "SELECT dr.id, qr.deployment_run_id, qr.deployment_member_item_id, i.project_id AS member_project_id "
        "FROM decision_requests dr "
        "JOIN qa_requirements qr "
        "ON CAST(qr.id AS TEXT) = dr.subject_key "
        "LEFT JOIN items i ON i.id = COALESCE(qr.deployment_member_item_id, qr.item_id) "
        f"WHERE dr.kind = {p} AND dr.subject_type = 'qa_requirement' "
        f"AND dr.status IN ('pending', 'resolved') "
        f"AND qr.deployment_run_id IN ({markers})",
        (QA_NEEDS_REVIEW, *run_ids),
    ).fetchall()
    return [
        (str(row["deployment_run_id"]), int(row["id"]))
        for row in rows
        if row["deployment_member_item_id"] is None
        or project_visible(row["member_project_id"], visible_project_ids)
    ]


def _member_approval_gates(conn: Any, run_ids: list[str]) -> list[tuple[str, int]]:
    """Find the latest done decision for each final member of each run."""
    p = _p(conn)
    markers = ", ".join(p for _ in run_ids)
    rows = conn.execute(
        "SELECT dri.run_id, MAX(dr.id) AS request_id "
        "FROM deployment_run_items dri JOIN decision_requests dr "
        "ON dr.subject_key=CAST(dri.item_id AS TEXT) || ':done' "
        f"WHERE dri.run_id IN ({markers}) AND dri.delivery_intent='final' "
        f"AND dr.kind={p} AND dr.subject_type='item_transition' "
        "AND dr.status IN ('pending','resolved') "
        "GROUP BY dri.run_id,dri.item_id",
        (*run_ids, LIFECYCLE_TRANSITION_APPROVAL),
    ).fetchall()
    return [(str(row["run_id"]), int(row["request_id"])) for row in rows]


def run_gates(
    conn: Any,
    run_ids: list[str],
    *,
    actor_id: Optional[int],
    visible_project_ids: set[int] | None = None,
    members: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return each run's approval record and pending gates.

    A gate can be visible even when the reader lacks authority to answer it.
    Project-owned gates and the member details inside a shared stage approval
    follow the same project boundary as the rest of the run card.
    """
    if not run_ids or not _table_exists(conn, "decision_requests"):
        return {}
    pairs = [
        *_stage_approval_gates(conn, run_ids),
        *_qa_review_gates(conn, run_ids, visible_project_ids),
        *_member_approval_gates(conn, run_ids),
    ]
    result: dict[str, list[dict[str, Any]]] = {}
    for run_id, request_id in pairs:
        request = _request_row(conn, request_id)
        if not project_visible(request.get("project_id"), visible_project_ids):
            continue
        record = gate_record(conn, request, actor_id=actor_id)
        if (
            visible_project_ids is not None
            and record["kind"] == DEPLOYMENT_STAGE_APPROVAL
        ):
            context = record["subject_context"]
            if batch := context.get("batch"):
                visible_ids = {item["id"] for item in (members or {}).get(run_id, ())}
                items = [
                    item
                    for item in batch.get("items", ())
                    if item["item_id"] in visible_ids
                ]
                if len(items) != batch["item_count"]:
                    shipping = context.get("shipping", {})
                    context = {
                        **context,
                        "batch": {"item_count": len(items), "items": items},
                        "shipping": {
                            **shipping,
                            "summary": f"{len(items)} visible item(s) ship to {shipping.get('target_environment', '')}.",
                        },
                    }
            if carried := context.get("carried"):
                context = {
                    **context,
                    "carried": visible_carried_work(
                        carried, request.get("project_id"), visible_project_ids
                    ),
                }
            record["subject_context"] = context
        result.setdefault(run_id, []).append(record)
    for gates in result.values():
        gates.sort(key=lambda gate: gate["request_id"])
    return temporal_wire(result)


__all__ = ["run_gates"]
