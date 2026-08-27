"""Why a quiet claim-holder is quiet: a declared wait, or an open probe.

A session that holds work and stops making tool calls is either waiting on
purpose or has simply stopped, and activity timestamps cannot tell those
apart. Two facts can. A *declared wait* is the session saying so — a turn
posture it parked itself in, or a dependency edge gating the item it holds,
which no amount of the session's own effort would clear. An *open probe* is
the stale-alive machinery having already asked the question, in which case
the answer is pending rather than unknown.

Roster readers render those as distinct states, so a session waiting by
declaration never presents as one suspected of being gone.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.dependencies import evaluate_satisfaction
from yoke_core.domain.dependency_types import is_coordination_only
from yoke_core.domain.dependency_workflow_context import (
    workflow_from_joined_values,
)
from yoke_core.domain.item_ref_columns import render_column_item_ref
from yoke_core.domain.item_worktree_resolution import (
    primary_item_worktree_branch_sql,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_stale_alive_probe import probe_key
from yoke_core.domain.work_claim_targets import scope_int_sql


#: Probe recipient states that mean the question is still outstanding. An
#: acknowledged probe was answered, and answering it takes a tool call, which
#: has already returned the session to active.
OPEN_PROBE_STATES = ("pending", "injected")

#: The turn posture a session parks itself in while it waits for an answer.
WAITING_TURN_POSTURE = "waiting"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _session_ids(rows: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(row.get("session_id") or "")
            for row in rows
            if row.get("session_id")
        )
    )


def _claimed_items(
    conn: Any,
    session_ids: Sequence[str],
) -> dict[str, list[int]]:
    """Internal item ids each session holds a live item claim on."""
    if not session_ids:
        return {}
    marker = _marker(conn)
    item_id = scope_int_sql(conn, "scope", "item_id")
    rows = conn.execute(
        f"SELECT session_id,{item_id} AS item_id FROM work_claims "
        "WHERE released_at IS NULL AND target_kind='item' AND session_id IN ("
        + ",".join(marker for _ in session_ids)
        + ") ORDER BY claimed_at,id",
        tuple(session_ids),
    ).fetchall()
    claimed: dict[str, list[int]] = {}
    for row in rows:
        if row["item_id"] is None:
            continue
        claimed.setdefault(str(row["session_id"]), []).append(int(row["item_id"]))
    return claimed


def _gating_blockers(
    conn: Any,
    item_ids: Sequence[int],
) -> dict[int, dict[str, Any]]:
    """The first unsatisfied gating blocker per dependent item, if any.

    Coordination-only edges are excluded: they attest that two items may
    touch a shared path, and gate nothing, so a session holding one side is
    not waiting on the other.
    """
    if not item_ids or not _table_exists(conn, "item_dependencies"):
        return {}
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT d.dependent_item_id,d.gate_point,d.satisfaction,"
        "d.blocking_item_id,b.status AS blocking_status,b.merged_at,"
        "b.workflow_id,b.workflow_version_id,wv.version,"
        "wv.definition_json,wv.definition_digest,"
        f"{primary_item_worktree_branch_sql('b.id')} AS lane_branch "
        "FROM item_dependencies d JOIN items b ON b.id=d.blocking_item_id "
        "LEFT JOIN workflow_versions wv ON wv.id=b.workflow_version_id "
        "WHERE d.dependent_item_id IN ("
        + ",".join(marker for _ in item_ids)
        + ") ORDER BY d.dependent_item_id,d.id",
        tuple(int(value) for value in item_ids),
    ).fetchall()
    blockers: dict[int, dict[str, Any]] = {}
    for row in rows:
        dependent = int(row["dependent_item_id"])
        if dependent in blockers or is_coordination_only(str(row["gate_point"])):
            continue
        workflow = workflow_from_joined_values(
            row["workflow_id"],
            row["workflow_version_id"],
            row["version"],
            row["definition_json"],
            row["definition_digest"],
        )
        verdict = evaluate_satisfaction(
            str(row["satisfaction"]),
            row["blocking_status"],
            row["lane_branch"],
            blocking_merged=True if row["merged_at"] else None,
            workflow=workflow,
        )
        if verdict.satisfied:
            continue
        blockers[dependent] = {
            "item": render_column_item_ref(conn, dependent),
            "blocking_item": render_column_item_ref(conn, row["blocking_item_id"]),
            "gate_point": str(row["gate_point"]),
            "blocking_status": str(row["blocking_status"] or ""),
        }
    return blockers


def _open_probes(
    conn: Any,
    session_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Sessions the stale-alive probe has asked and not yet heard back from."""
    if not session_ids or not _table_exists(conn, "session_message_recipients"):
        return {}
    marker = _marker(conn)
    state_markers = ",".join(marker for _ in OPEN_PROBE_STATES)
    rows = conn.execute(
        "SELECT r.session_id,r.state,r.created_at,r.wake_attempt_count "
        "FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "WHERE m.cancelled_at IS NULL AND r.state IN ("
        + state_markers
        + ") AND m.idempotency_key IN ("
        + ",".join(marker for _ in session_ids)
        + ") AND r.session_id IN ("
        + ",".join(marker for _ in session_ids)
        + ") ORDER BY r.created_at DESC,r.message_id DESC",
        (
            *OPEN_PROBE_STATES,
            *(probe_key(session_id) for session_id in session_ids),
            *session_ids,
        ),
    ).fetchall()
    probes: dict[str, dict[str, Any]] = {}
    for row in rows:
        session_id = str(row["session_id"])
        if session_id in probes:
            continue
        probes[session_id] = {
            "state": str(row["state"]),
            "created_at": row["created_at"],
            "wake_attempt_count": int(row["wake_attempt_count"] or 0),
        }
    return probes


def session_health_facts(
    conn: Any,
    rows: list[dict[str, Any]],
    identities: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Project declared-wait and open-probe facts for roster rows."""
    session_ids = _session_ids(rows)
    claimed = _claimed_items(conn, session_ids)
    blockers = _gating_blockers(
        conn,
        sorted({item for items in claimed.values() for item in items}),
    )
    probes = _open_probes(conn, session_ids)
    projected: dict[str, dict[str, Any]] = {}
    for session_id in session_ids:
        identity = identities.get(session_id, {})
        declared: dict[str, Any] | None = None
        for item in claimed.get(session_id, []):
            if item in blockers:
                declared = {"kind": "dependency", **blockers[item]}
                break
        if declared is None and identity.get("turn_posture") == WAITING_TURN_POSTURE:
            declared = {"kind": "turn_posture"}
        projected[session_id] = {
            "declared_wait": declared,
            "stale_alive_probe": probes.get(session_id),
        }
    return projected


__all__ = [
    "OPEN_PROBE_STATES",
    "WAITING_TURN_POSTURE",
    "session_health_facts",
]
