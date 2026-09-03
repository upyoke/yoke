"""Item-dependency graph commands for ``item_dependencies`` rows."""
from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.dependency_satisfaction import require_authorable_satisfaction
from yoke_core.domain.item_ref_columns import resolve_column_item_ref
from yoke_core.domain.path_claims_blocked_reason_refresh import (
    refresh_blocked_reason_for_edge_change,
)
from yoke_core.domain.shepherd_records import (
    normalize_item_id,
    now_iso,
    read_stdin_safe,
)


def _edge_ids(conn, dependent: str, blocking: str) -> tuple[int, int]:
    """Resolve API tokens to the integer ids stored on the edge."""
    dep_id = resolve_column_item_ref(conn, normalize_item_id(dependent, conn))
    blk_id = resolve_column_item_ref(conn, normalize_item_id(blocking, conn))
    if dep_id is None or blk_id is None:
        raise LookupError(
            f"item not found for dependency {dependent}->{blocking}"
        )
    return dep_id, blk_id


def _refresh_blocked_reasons(conn, dep_id: int, blk_id: int) -> None:
    """Trigger wording refresh after an item_dependencies edge change."""
    refresh_blocked_reason_for_edge_change(
        conn,
        dependent_item_id=dep_id,
        blocking_item_id=blk_id,
    )

VALID_GATE_POINTS = frozenset({"activation", "integration", "closure", "coordination_only"})
VALID_SOURCES = frozenset(
    {"operator", "shepherd", "conduct", "feed", "migration", "idea", "refine"}
)

_DEFAULT_SATISFACTION = {
    "activation": "status:done",
    "integration": "fact:merged",
    "closure": "status:done",
    "coordination_only": "fact:merged",
}


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def cmd_dependency_add(
    conn,
    dependent: str,
    blocking: str,
    source: str,
    gate_point: str = "activation",
    satisfaction: Optional[str] = None,
    rationale: Optional[str] = None,
    evidence_json: str = "{}",
    session_id: Optional[int] = None,
) -> str:
    _validate_dependency_fields(source, gate_point)
    dep_id, blk_id = _edge_ids(conn, dependent, blocking)

    satisfaction = satisfaction or _DEFAULT_SATISFACTION.get(gate_point, "status:done")
    require_authorable_satisfaction(
        conn,
        blocking_item_id=blk_id,
        satisfaction=satisfaction,
    )
    rationale = rationale or f"Operator-declared {gate_point} dependency"
    p = _placeholder(conn)
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id, blocking_item_id, gate_point, satisfaction, source, "
        "session_id, rationale, evidence_json, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
        "ON CONFLICT(dependent_item_id, blocking_item_id, gate_point) DO NOTHING",
        (
            dep_id,
            blk_id,
            gate_point,
            satisfaction,
            source,
            session_id,
            rationale,
            evidence_json,
            now_iso(),
        ),
    )
    conn.commit()
    _refresh_blocked_reasons(conn, dep_id, blk_id)
    return "OK"


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
) -> str:
    dep_id, blk_id = _edge_ids(conn, dependent, blocking)
    _validate_dependency_update_inputs(match_gate_point, gate_point, satisfaction, rationale)
    if satisfaction:
        require_authorable_satisfaction(
            conn,
            blocking_item_id=blk_id,
            satisfaction=satisfaction,
        )

    p = _placeholder(conn)
    where_parts = [f"dependent_item_id={p}", f"blocking_item_id={p}"]
    params: list = [dep_id, blk_id]
    if match_gate_point:
        where_parts.append(f"gate_point={p}")
        params.append(match_gate_point)
    where = " AND ".join(where_parts)
    _ensure_single_dependency_match(conn, where, params, dependent, blocking, match_gate_point)
    _ensure_gate_point_update_is_available(conn, where, params, dependent, blocking, gate_point)

    set_parts = []
    set_params: list = []
    if gate_point:
        set_parts.append(f"gate_point={p}")
        set_params.append(gate_point)
    if satisfaction:
        set_parts.append(f"satisfaction={p}")
        set_params.append(satisfaction)
    if rationale:
        set_parts.append(f"rationale={p}")
        set_params.append(rationale)

    conn.execute(
        f"UPDATE item_dependencies SET {', '.join(set_parts)} WHERE {where}",
        tuple(set_params + params),
    )
    conn.commit()
    _refresh_blocked_reasons(conn, dep_id, blk_id)
    return "OK"


def _validate_dependency_update_inputs(
    match_gate_point: Optional[str],
    gate_point: Optional[str],
    satisfaction: Optional[str],
    rationale: Optional[str],
) -> None:
    if not any([gate_point, satisfaction, rationale]):
        raise ValueError("at least one of --gate-point, --satisfaction, --rationale required")
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
        f"WHERE dependent_item_id={_placeholder(conn)} "
        f"AND blocking_item_id={_placeholder(conn)} "
        f"AND gate_point={_placeholder(conn)}",
        (params[0], params[1], gate_point),
    )
    if conflict:
        raise ValueError(f"cannot change gate_point to {gate_point} — edge already exists")


def cmd_dependency_reconcile(
    conn,
    source: str,
    scope_item: str,
    gate_point_filter: Optional[str] = None,
    stdin_lines: Optional[List[str]] = None,
) -> str:
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be {', '.join(sorted(VALID_SOURCES))}")
    scope_id = resolve_column_item_ref(conn, normalize_item_id(scope_item, conn))
    if scope_id is None:
        raise LookupError(f"item not found: {scope_item}")
    if gate_point_filter and gate_point_filter not in VALID_GATE_POINTS:
        raise ValueError(f"invalid gate_point: {gate_point_filter}")

    delete_params: list = [source, scope_id]
    p = _placeholder(conn)
    delete_where = f"source={p} AND dependent_item_id={p}"
    if gate_point_filter:
        delete_where += f" AND gate_point={p}"
        delete_params.append(gate_point_filter)

    if stdin_lines is None:
        raw = read_stdin_safe() or sys.stdin.read()
        stdin_lines = [line for line in raw.strip().split("\n") if line.strip()]

    edges = []
    ts = now_iso()
    for line in stdin_lines:
        edge = _parse_dependency_edge(conn, line, source, ts)
        if edge is not None:
            edges.append(edge)
    prior_pairs = {
        (int(row[0]), int(row[1]))
        for row in conn.execute(
            f"SELECT dependent_item_id, blocking_item_id "
            f"FROM item_dependencies WHERE {delete_where}",
            tuple(delete_params),
        ).fetchall()
    }
    conn.execute("BEGIN")
    conn.execute(f"DELETE FROM item_dependencies WHERE {delete_where}", tuple(delete_params))
    for edge in edges:
        conn.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item_id, blocking_item_id, gate_point, satisfaction, source, "
            f"rationale, evidence_json, created_at) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
            "ON CONFLICT(dependent_item_id, blocking_item_id, gate_point) DO NOTHING",
            edge,
        )
    conn.execute("COMMIT")
    refreshed_pairs = prior_pairs | {(int(edge[0]), int(edge[1])) for edge in edges}
    for dependent, blocking in sorted(refreshed_pairs):
        _refresh_blocked_reasons(conn, dependent, blocking)
    return "OK"


def _parse_dependency_edge(conn, line: str, source: str, ts: str) -> tuple | None:
    parts = line.split()
    if len(parts) < 4:
        return None
    dependent, blocking = _edge_ids(conn, parts[0], parts[1])
    gate_point = parts[2]
    satisfaction = parts[3]
    rationale = " ".join(parts[4:]) if len(parts) > 4 else ""
    if gate_point not in VALID_GATE_POINTS:
        raise ValueError(f"invalid gate_point in stdin: {gate_point}")
    require_authorable_satisfaction(
        conn,
        blocking_item_id=blocking,
        satisfaction=satisfaction,
    )
    return (dependent, blocking, gate_point, satisfaction, source, rationale, "{}", ts)


def cmd_dependency_remove(
    conn,
    dependent: str,
    blocking: str,
    session_id: Optional[int] = None,
) -> str:
    dep_id, blk_id = _edge_ids(conn, dependent, blocking)
    if session_id is not None:
        p = _placeholder(conn)
        conn.execute(
            "DELETE FROM item_dependencies "
            f"WHERE dependent_item_id={p} AND blocking_item_id={p} AND session_id={p}",
            (dep_id, blk_id, session_id),
        )
    else:
        p = _placeholder(conn)
        conn.execute(
            f"DELETE FROM item_dependencies WHERE dependent_item_id={p} AND blocking_item_id={p}",
            (dep_id, blk_id),
        )
    conn.commit()
    _refresh_blocked_reasons(conn, dep_id, blk_id)
    return "OK"

