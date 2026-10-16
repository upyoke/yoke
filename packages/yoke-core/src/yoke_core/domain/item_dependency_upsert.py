"""Create-or-update of one ``item_dependencies`` edge with a truthful report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend

_EDGE_COLUMNS = "id, gate_point, satisfaction, source, rationale, evidence_json"
_UPDATABLE_FIELDS = ("source", "satisfaction", "rationale", "evidence_json")
_SHOWN_CHARS = 60


@dataclass(frozen=True)
class DependencyEdge:
    """The stored values of one edge."""

    dependency_id: int
    gate_point: str
    satisfaction: str
    source: str
    rationale: str
    evidence_json: str


@dataclass(frozen=True)
class DependencyWrite:
    """What ``write_dependency_edge`` did, with the row as stored afterwards."""

    edge: DependencyEdge
    action: str  # created | updated | unchanged
    changes: tuple[tuple[str, str, str], ...] = ()  # (field, old, new)

    @property
    def message(self) -> str:
        number = self.edge.dependency_id
        if self.action == "created":
            return f"created dependency #{number}"
        if self.action == "unchanged":
            return f"unchanged: existing dependency #{number}"
        shown = "; ".join(
            f"{field} {_shown(old)} -> {_shown(new)}"
            for field, old, new in self.changes
        )
        return f"updated existing dependency #{number}: {shown}"


def _shown(value: str) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= _SHOWN_CHARS else f"{text[:_SHOWN_CHARS]}..."


def placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def read_dependency_edge(
    conn: Any, dep_id: int, blk_id: int, gate_point: str
) -> Optional[DependencyEdge]:
    p = placeholder(conn)
    row = conn.execute(
        f"SELECT {_EDGE_COLUMNS} FROM item_dependencies "
        f"WHERE dependent_item_id={p} AND blocking_item_id={p} AND gate_point={p}",
        (dep_id, blk_id, gate_point),
    ).fetchone()
    if row is None:
        return None
    return DependencyEdge(int(row[0]), *(str(value) for value in row[1:]))


def write_dependency_edge(
    conn: Any,
    existing: Optional[DependencyEdge],
    dep_id: int,
    blk_id: int,
    gate_point: str,
    *,
    source: str,
    satisfaction: Optional[str],
    rationale: Optional[str],
    evidence_json: Optional[str],
    session_id: Optional[int],
    created_at: Any,
) -> DependencyWrite:
    """Insert the edge, or update the fields that differ on ``existing``.

    ``existing`` is the row ``read_dependency_edge`` returned for this edge.
    On an existing edge a field passed as ``None`` keeps its stored value; on
    a new edge ``satisfaction`` must be set and the others take their defaults.
    """
    p = placeholder(conn)
    if existing is None:
        conn.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item_id, blocking_item_id, gate_point, satisfaction, source, "
            "session_id, rationale, evidence_json, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            (
                dep_id,
                blk_id,
                gate_point,
                satisfaction,
                source,
                session_id,
                rationale or f"Operator-declared {gate_point} dependency",
                evidence_json or "{}",
                created_at,
            ),
        )
        action, changes = "created", ()
    else:
        wanted = dict(
            zip(_UPDATABLE_FIELDS, (source, satisfaction, rationale, evidence_json))
        )
        changes = tuple(
            (field, getattr(existing, field), value)
            for field, value in wanted.items()
            if value is not None and value != getattr(existing, field)
        )
        if changes:
            assignments = ", ".join(f"{field}={p}" for field, _, _ in changes)
            conn.execute(
                f"UPDATE item_dependencies SET {assignments} WHERE id={p}",
                (*(new for _, _, new in changes), existing.dependency_id),
            )
        action = "updated" if changes else "unchanged"
    stored = read_dependency_edge(conn, dep_id, blk_id, gate_point)
    assert stored is not None
    return DependencyWrite(stored, action, changes)
