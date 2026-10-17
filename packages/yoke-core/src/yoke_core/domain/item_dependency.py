"""Item-dependency graph commands for ``item_dependencies`` rows."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.dependency_values import VALID_GATE_POINTS, VALID_SOURCES

from yoke_core.domain.db_helpers import instant_parameter, query_scalar
from yoke_core.domain.dependency_cycles_read import refuse_cycles_through
from yoke_core.domain.dependency_satisfaction import require_authorable_satisfaction
from yoke_core.domain.item_dependency_upsert import (
    DependencyWrite,
    placeholder,
    read_dependency_edge,
    write_dependency_edge,
)
from yoke_core.domain.item_ref_resolution import resolve_item_ref
from yoke_core.domain.path_claims_blocked_reason_refresh import (
    refresh_blocked_reason_for_edge_change,
)
from yoke_core.domain.shepherd_records import now_iso


def _edge_ids(conn, dependent: str, blocking: str) -> tuple[int, int]:
    """Resolve the edge's two public refs to the integer ids it stores."""
    return resolve_item_ref(conn, dependent), resolve_item_ref(conn, blocking)


def _refresh_blocked_reasons(conn, dep_id: int, blk_id: int) -> None:
    """Reclassify blocked reservations after an item dependency changes."""
    refresh_blocked_reason_for_edge_change(
        conn,
        dependent_item_id=dep_id,
        blocking_item_id=blk_id,
    )


HARD_BLOCK_GATE_POINTS = VALID_GATE_POINTS - {"coordination_only"}

_DEFAULT_SATISFACTION = {
    "activation": "status:done",
    "integration": "fact:merged",
    "closure": "status:done",
    "coordination_only": "fact:merged",
}


def cmd_dependency_add(
    conn,
    dependent: str,
    blocking: str,
    source: str,
    gate_point: str = "activation",
    satisfaction: Optional[str] = None,
    rationale: Optional[str] = None,
    evidence_json: Optional[str] = None,
    session_id: Optional[str] = None,
) -> DependencyWrite:
    """Create the edge, or update the fields that differ on an existing one.

    On an existing edge a field left ``None`` keeps its stored value.
    ``session_id`` records the session that authored a new edge. A write that
    would close a loop of blocking edges among live items rolls back and
    raises :class:`DependencyCycleError` naming the loop and its recovery.
    """
    _validate_dependency_fields(source, gate_point)
    dep_id, blk_id = _edge_ids(conn, dependent, blocking)
    created_at = instant_parameter(conn, now_iso())

    existing = read_dependency_edge(conn, dep_id, blk_id, gate_point)
    if satisfaction or existing is None:
        satisfaction = satisfaction or _DEFAULT_SATISFACTION.get(
            gate_point, "status:done"
        )
        require_authorable_satisfaction(
            conn,
            blocking_item_id=blk_id,
            satisfaction=satisfaction,
        )
    write = write_dependency_edge(
        conn,
        existing,
        dep_id,
        blk_id,
        gate_point,
        source=source,
        satisfaction=satisfaction,
        rationale=rationale,
        evidence_json=evidence_json,
        session_id=session_id,
        created_at=created_at,
    )
    refuse_cycles_through(
        conn,
        [write.edge.dependency_id],
        f"adding {dependent} waiting on {blocking} at {gate_point}",
    )
    conn.commit()
    _refresh_blocked_reasons(conn, dep_id, blk_id)
    return write


def _validate_dependency_fields(
    source: str,
    gate_point: str,
) -> None:
    if gate_point not in VALID_GATE_POINTS:
        raise ValueError(f"gate_point must be {', '.join(sorted(VALID_GATE_POINTS))}")
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be {', '.join(sorted(VALID_SOURCES))}")


def cmd_dependency_update(
    conn,
    dependent: str,
    blocking: str,
    match_gate_point: Optional[str] = None,
    gate_point: Optional[str] = None,
    satisfaction: Optional[str] = None,
    rationale: Optional[str] = None,
    source: Optional[str] = None,
    evidence_json: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Change one edge's fields, recording ``session_id`` as its author.

    A gate or satisfaction change that would leave the edge closing a loop of
    blocking edges among live items rolls back and raises
    :class:`DependencyCycleError`.
    """
    dep_id, blk_id = _edge_ids(conn, dependent, blocking)
    _validate_dependency_update_inputs(
        match_gate_point, gate_point, satisfaction, rationale, source, evidence_json
    )
    if satisfaction:
        require_authorable_satisfaction(
            conn,
            blocking_item_id=blk_id,
            satisfaction=satisfaction,
        )

    p = placeholder(conn)
    where_parts = [f"dependent_item_id={p}", f"blocking_item_id={p}"]
    params: list = [dep_id, blk_id]
    if match_gate_point:
        where_parts.append(f"gate_point={p}")
        params.append(match_gate_point)
    where = " AND ".join(where_parts)
    _ensure_single_dependency_match(
        conn, where, params, dependent, blocking, match_gate_point
    )
    _ensure_gate_point_update_is_available(
        conn, where, params, dependent, blocking, gate_point
    )

    set_parts = []
    set_params: list = []
    for column, value in (
        ("gate_point", gate_point),
        ("satisfaction", satisfaction),
        ("rationale", rationale),
        ("source", source),
        ("evidence_json", evidence_json),
        ("session_id", session_id),
    ):
        if value:
            set_parts.append(f"{column}={p}")
            set_params.append(value)

    edge_ids = [
        int(row[0])
        for row in conn.execute(
            f"SELECT id FROM item_dependencies WHERE {where}", tuple(params)
        ).fetchall()
    ]
    conn.execute(
        f"UPDATE item_dependencies SET {', '.join(set_parts)} WHERE {where}",
        tuple(set_params + params),
    )
    if gate_point or satisfaction:
        refuse_cycles_through(
            conn,
            edge_ids,
            f"updating {dependent} waiting on {blocking}"
            + (f" to {gate_point}" if gate_point else ""),
        )
    conn.commit()
    _refresh_blocked_reasons(conn, dep_id, blk_id)
    return "OK"


def _validate_dependency_update_inputs(
    match_gate_point: Optional[str],
    gate_point: Optional[str],
    satisfaction: Optional[str],
    rationale: Optional[str],
    source: Optional[str],
    evidence_json: Optional[str],
) -> None:
    if not any([gate_point, satisfaction, rationale, source, evidence_json]):
        raise ValueError(
            "at least one of --gate-point, --satisfaction, --rationale, --source, "
            "--evidence required"
        )
    if source and source not in VALID_SOURCES:
        raise ValueError(f"source must be {', '.join(sorted(VALID_SOURCES))}")
    if match_gate_point and match_gate_point not in VALID_GATE_POINTS:
        raise ValueError(f"invalid match gate_point: {match_gate_point}")
    if gate_point and gate_point not in VALID_GATE_POINTS:
        raise ValueError(f"invalid gate_point: {gate_point}")


def _ensure_single_dependency_match(
    conn,
    where: str,
    params: list,
    dependent: str,
    blocking: str,
    match_gate_point: Optional[str],
) -> None:
    count = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM item_dependencies WHERE {where}",
        tuple(params),
    )
    if not count:
        raise LookupError(
            f"no dependency edge found for dependent={dependent} blocking={blocking}"
            + (f" gate_point={match_gate_point}" if match_gate_point else "")
        )
    if not match_gate_point and count > 1:
        raise ValueError(
            f"multiple edges found for {dependent}->{blocking}. "
            "Use --match-gate-point to disambiguate."
        )


def _ensure_gate_point_update_is_available(
    conn,
    where: str,
    params: list,
    dependent: str,
    blocking: str,
    gate_point: Optional[str],
) -> None:
    if not gate_point:
        return
    current_gp = query_scalar(
        conn,
        f"SELECT gate_point FROM item_dependencies WHERE {where} ORDER BY gate_point LIMIT 1",
        tuple(params),
    )
    if gate_point == current_gp:
        return
    conflict = query_scalar(
        conn,
        "SELECT COUNT(*) FROM item_dependencies "
        f"WHERE dependent_item_id={placeholder(conn)} "
        f"AND blocking_item_id={placeholder(conn)} "
        f"AND gate_point={placeholder(conn)}",
        (params[0], params[1], gate_point),
    )
    if conflict:
        raise ValueError(
            f"cannot change gate_point to {gate_point} — edge already exists"
        )


def cmd_dependency_remove(
    conn,
    dependent: str,
    blocking: str,
    session_id: Optional[str] = None,
) -> str:
    dep_id, blk_id = _edge_ids(conn, dependent, blocking)
    if session_id is not None:
        p = placeholder(conn)
        conn.execute(
            "DELETE FROM item_dependencies "
            f"WHERE dependent_item_id={p} AND blocking_item_id={p} AND session_id={p}",
            (dep_id, blk_id, session_id),
        )
    else:
        p = placeholder(conn)
        conn.execute(
            f"DELETE FROM item_dependencies WHERE dependent_item_id={p} AND blocking_item_id={p}",
            (dep_id, blk_id),
        )
    conn.commit()
    _refresh_blocked_reasons(conn, dep_id, blk_id)
    return "OK"
