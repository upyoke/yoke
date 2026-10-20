"""Tell a dependent's lane when its blocker's gate on it becomes satisfied.

Landing and the transition to done change what a blocker has proved, and
path-claim propagation already reclassifies the dependent's reservations.
The dependent's session still has to hear about it: a parked worker that
nobody tells keeps waiting. This reads every ordering edge the blocker
gates, and for each edge the canonical evaluator now reports satisfied,
sends one notice through the same lane routing landing notices use. The
notice names the blocker, the gate and what it proved, plus any gates on
the dependent that remain unmet so the reader knows whether to resume.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from yoke_contracts.timestamps import utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.dependency_satisfaction import evaluate_persisted_satisfaction
from yoke_core.domain.dependency_types import GateResult, is_activation_gate
from yoke_core.domain.merge_queue_landing_notice import HOLDER, push_notice
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

#: The gate point that attests compatible edits and gates nothing.
COORDINATION_ONLY = "coordination_only"

#: Blocker events that can satisfy a dependent's gate.
EVENT_MERGED = "merged"
EVENT_DONE = "reached done"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def dependency_satisfied_key(
    dependent_id: int, blocker_id: int, gate_point: str, dependency_id: int
) -> str:
    """One notice per durable edge, allowing a newly created wait to notify again."""
    return (
        f"dependency-satisfied:{int(dependent_id)}:{int(blocker_id)}:"
        f"{gate_point}:{int(dependency_id)}"
    )


def _blocker_verdict(
    conn: Any, blocker_id: int, satisfaction: str, created_at: Any
) -> GateResult:
    """Evaluate one gate against the blocker's recorded status and landing."""
    p = _p(conn)
    row = conn.execute(
        f"SELECT status, merged_at FROM items WHERE id={p}", (int(blocker_id),)
    ).fetchone()
    if row is None:
        return GateResult(False, "Blocking item no longer exists.")
    merged = bool(row[1])
    if not merged and _table_exists(conn, "item_landings"):
        merged = (
            conn.execute(
                f"SELECT 1 FROM item_landings WHERE item_id={p} LIMIT 1",
                (int(blocker_id),),
            ).fetchone()
            is not None
        )
    return evaluate_persisted_satisfaction(
        conn,
        blocking_item_id=int(blocker_id),
        satisfaction=satisfaction,
        blocking_status=str(row[0] or ""),
        blocking_merged=True if merged else None,
        blocking_merged_at=row[1],
        dependency_created_at=created_at,
        workflow=load_item_workflow_runtime(conn, int(blocker_id)),
    )


def _ordering_edges(
    conn: Any, column: str, item_id: int
) -> list[tuple[int, int, str, str, Any, int]]:
    """Ordering edges touching ``item_id`` as ``column``; coordination excluded."""
    p = _p(conn)
    rows = conn.execute(
        "SELECT dependent_item_id, blocking_item_id, gate_point, "
        f"COALESCE(satisfaction, 'status:done'), created_at, id FROM item_dependencies "
        f"WHERE {column}={p} AND gate_point<>{p} ORDER BY id",
        (int(item_id), COORDINATION_ONLY),
    ).fetchall()
    return [
        (int(r[0]), int(r[1]), str(r[2]), str(r[3]).strip(), r[4], int(r[5]))
        for r in rows
    ]


def _remaining_gates(
    conn: Any, dependent_id: int, blocker_id: int
) -> list[dict[str, str]]:
    """Every other unmet gate on the dependent, named for its reader."""
    remaining = []
    for _, other, gate_point, satisfaction, created_at, _edge_id in _ordering_edges(
        conn, "dependent_item_id", dependent_id
    ):
        if other == blocker_id:
            continue
        if not _blocker_verdict(conn, other, satisfaction, created_at).satisfied:
            remaining.append(
                {
                    "blocker_ref": render_item_ref(conn, other),
                    "gate_point": gate_point,
                    "satisfaction": satisfaction,
                }
            )
    return remaining


def satisfied_message(
    route: str,
    *,
    blocker_ref: str,
    dependent_ref: str,
    event: str,
    gate_point: str,
    satisfaction: str,
    remaining: list[dict[str, str]],
) -> str:
    """Name what the blocker proved, which gate it cleared and what is left."""
    descriptions = [
        f"{gate['blocker_ref']} {gate['gate_point']} gate {gate['satisfaction']}"
        for gate in remaining
    ]
    still = (
        f" Still unmet: {'; '.join(descriptions)} — keep waiting on those; "
        "another notice follows when each clears."
        if remaining
        else " No other dependency gates remain."
    )
    if route == HOLDER:
        lead = (
            f"{blocker_ref} {event}; your {gate_point} gate {satisfaction} on "
            f"{dependent_ref} is satisfied"
        )
        action = " — continue the step this gate held." if not remaining else "."
        return lead + action + still
    activation = [
        gate["blocker_ref"]
        for gate in remaining
        if is_activation_gate(gate["gate_point"])
    ]
    action = (
        f"{dependent_ref} still waits on {'; '.join(activation)} activation gate; "
        "do not staff it yet."
        if activation
        else "Route normal staffing so its work resumes."
    )
    return (
        f"{blocker_ref} {event}; {dependent_ref}'s {gate_point} gate "
        f"{satisfaction} is satisfied, but {dependent_ref} has no live claim "
        f"holder. {action}" + still
    )


def notify_satisfied_dependents(
    conn: Any, *, blocking_item_id: int, event: str
) -> list[dict[str, str]]:
    """Send each newly satisfied dependent one notice on ``conn``; no commit.

    Dependents already at a terminal stage are skipped. Delivery reports use
    :func:`push_notice`'s vocabulary, with ``""`` for nobody addressable.
    """
    blocker_ref = render_item_ref(conn, blocking_item_id)
    now = utc_now()
    reports = []
    for (
        dependent_id,
        _,
        gate_point,
        satisfaction,
        created_at,
        edge_id,
    ) in _ordering_edges(conn, "blocking_item_id", blocking_item_id):
        if not _blocker_verdict(
            conn, blocking_item_id, satisfaction, created_at
        ).satisfied:
            continue
        row = conn.execute(
            f"SELECT project_id, status FROM items WHERE id={_p(conn)}",
            (dependent_id,),
        ).fetchone()
        if row is None:
            continue
        workflow = load_item_workflow_runtime(conn, dependent_id)
        if str(row[1] or "") in workflow.terminal_stage_ids:
            continue
        dependent_ref = render_item_ref(conn, dependent_id)
        remaining = _remaining_gates(conn, dependent_id, blocking_item_id)
        delivery = push_notice(
            conn,
            item_id=dependent_id,
            project_id=int(row[0]),
            body_for_route=partial(
                satisfied_message,
                blocker_ref=blocker_ref,
                dependent_ref=dependent_ref,
                event=event,
                gate_point=gate_point,
                satisfaction=satisfaction,
                remaining=remaining,
            ),
            idempotency_key=dependency_satisfied_key(
                dependent_id, blocking_item_id, gate_point, edge_id
            ),
            now=now,
        )
        reports.append(
            {"dependent": dependent_ref, "gate_point": gate_point, "delivery": delivery}
        )
    return reports


def notify_after_commit(
    conn: Any, *, blocking_item_id: int, event: str
) -> tuple[list[dict[str, str]], str]:
    """Notify in its own transaction after the caller's write committed.

    A failure rolls back only the notices and returns a named advisory with
    its recovery; the landing or transition that triggered it stays durable.
    """
    try:
        reports = notify_satisfied_dependents(
            conn, blocking_item_id=blocking_item_id, event=event
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - notices never reverse the trigger
        conn.rollback()
        ref = render_item_ref(conn, blocking_item_id)
        return [], (
            f"dependency_notice_deferred: dependents of {ref} were not told "
            f"their gate cleared ({exc}). Read `yoke items dependency list "
            f"{ref}` and message each satisfied dependent's holder."
        )
    return reports, ""


__all__ = [
    "EVENT_DONE",
    "EVENT_MERGED",
    "dependency_satisfied_key",
    "notify_after_commit",
    "notify_satisfied_dependents",
    "satisfied_message",
]
