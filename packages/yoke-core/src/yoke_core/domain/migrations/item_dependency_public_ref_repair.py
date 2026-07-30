"""Rewrite dependency edge refs that stored an internal item id.

``item_dependencies.dependent_item`` and ``item_dependencies.blocking_item``
hold PUBLIC item refs — ``projects.public_item_prefix || '-' ||
items.project_sequence``. A writer that instead stored ``items.id`` behind a
hardcoded prefix produces a value that is indistinguishable from a public ref
whenever the two numbers happen to coincide, and silently wrong when they do
not.

This module repairs the divergent values without hardcoding row ids: a value
is rewritten only when it fails to resolve as a public ref AND its numeric
tail resolves as an internal ``items.id``. Values that already resolve as a
public ref are left untouched; values that resolve under neither reading carry
no recoverable intent and are reported rather than guessed at.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


MIGRATION_NAME = "item_dependency_public_ref_repair"

REQUIRED_TABLES = ("items", "projects", "item_dependencies")

#: The two columns that store public item refs, in ``SELECT`` order.
REF_COLUMNS = ("dependent_item", "blocking_item")

#: A rewrite set larger than this means the malformed-ref population changed
#: materially since the repair shape was assessed. Abort rather than rewrite
#: an unreviewed volume of live coordination edges.
MAX_REWRITES = 20

#: ``(dependency_id, column, old_value, new_value)``
Rewrite = Tuple[int, str, str, str]
#: ``(dependency_id, column, value)``
Unresolvable = Tuple[int, str, str]
#: ``(dependency_id, column, value, public_item_id, internal_item_id)``
Ambiguous = Tuple[int, str, str, int, int]


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _field(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _numeric_tail(value: str) -> Optional[int]:
    prefix, separator, tail = value.rpartition("-")
    if not separator or not prefix or not tail.isdigit():
        return None
    return int(tail)


def _ref_maps(conn: Any) -> Tuple[Dict[str, int], Dict[int, str]]:
    """Return public-ref → item id and item id → public-ref lookups."""
    rows = conn.execute(
        "SELECT i.id AS id, "
        "p.public_item_prefix || '-' || i.project_sequence AS ref "
        "FROM items i JOIN projects p ON p.id = i.project_id "
        "WHERE i.project_sequence IS NOT NULL "
        "AND p.public_item_prefix IS NOT NULL"
    ).fetchall()
    by_ref: Dict[str, int] = {}
    by_id: Dict[int, str] = {}
    for row in rows:
        item_id = int(_field(row, "id", 0))
        ref = str(_field(row, "ref", 1))
        by_ref[ref] = item_id
        by_id[item_id] = ref
    return by_ref, by_id


def classify(conn: Any) -> Tuple[List[Rewrite], List[Unresolvable], List[Ambiguous]]:
    """Split every stored ref into rewrite, unresolvable, and ambiguous sets."""
    by_ref, by_id = _ref_maps(conn)
    rewrites: List[Rewrite] = []
    unresolvable: List[Unresolvable] = []
    ambiguous: List[Ambiguous] = []
    rows = conn.execute(
        f"SELECT id, {', '.join(REF_COLUMNS)} FROM item_dependencies ORDER BY id"
    ).fetchall()
    for row in rows:
        dependency_id = int(_field(row, "id", 0))
        for offset, column in enumerate(REF_COLUMNS, start=1):
            raw = _field(row, column, offset)
            if raw is None or not str(raw).strip():
                continue
            value = str(raw)
            public_item = by_ref.get(value)
            tail = _numeric_tail(value)
            internal_item = tail if tail in by_id else None
            if public_item is not None:
                if internal_item is not None and internal_item != public_item:
                    ambiguous.append(
                        (dependency_id, column, value, public_item, internal_item)
                    )
                continue
            if internal_item is None:
                unresolvable.append((dependency_id, column, value))
                continue
            rewrites.append((dependency_id, column, value, by_id[internal_item]))
    return rewrites, unresolvable, ambiguous


def _require_tables(conn: Any) -> None:
    missing = [table for table in REQUIRED_TABLES if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            f"{MIGRATION_NAME} requires deployed tables: " + ", ".join(missing)
        )


def _assert_no_edge_collisions(conn: Any, rewrites: List[Rewrite]) -> None:
    """Refuse a rewrite that would duplicate an existing coordination edge.

    ``item_dependencies`` is unique on ``(dependent_item, blocking_item,
    gate_point)``. A repaired ref can land on an edge that already exists, and
    an opaque constraint violation mid-apply is a poor operator signal.
    """
    pending = {(dependency_id, column): new for dependency_id, column, _, new in rewrites}
    if not pending:
        return
    rows = conn.execute(
        f"SELECT id, {', '.join(REF_COLUMNS)}, gate_point FROM item_dependencies"
    ).fetchall()
    keys: Dict[Tuple[str, str, str], int] = {}
    collisions: List[str] = []
    for row in rows:
        dependency_id = int(_field(row, "id", 0))
        values = [
            str(pending.get((dependency_id, column), _field(row, column, offset)))
            for offset, column in enumerate(REF_COLUMNS, start=1)
        ]
        key = (values[0], values[1], str(_field(row, "gate_point", len(REF_COLUMNS) + 1)))
        if key in keys:
            collisions.append(f"{keys[key]} and {dependency_id} both become {key}")
        keys[key] = dependency_id
    if collisions:
        raise RuntimeError(
            f"{MIGRATION_NAME} would collapse distinct dependency edges: "
            + "; ".join(collisions)
        )


def apply(conn: Any) -> None:
    """Rewrite every recoverable internal-id ref into its true public ref."""
    _require_tables(conn)
    rewrites, unresolvable, ambiguous = classify(conn)

    for dependency_id, column, value, public_item, internal_item in ambiguous:
        print(
            f"{MIGRATION_NAME}: AMBIGUOUS {dependency_id} / {column} / {value} "
            f"resolves as public ref item {public_item} and as internal id "
            f"{internal_item}; intent is unrecoverable, leaving unchanged"
        )
    for dependency_id, column, value in unresolvable:
        print(
            f"{MIGRATION_NAME}: UNRESOLVABLE {dependency_id} / {column} / {value} "
            "matches no public ref and no internal item id; leaving unchanged"
        )

    if len(rewrites) > MAX_REWRITES:
        raise RuntimeError(
            f"{MIGRATION_NAME} found {len(rewrites)} malformed refs, above the "
            f"{MAX_REWRITES} rewrite bound; reassess the population before applying"
        )
    _assert_no_edge_collisions(conn, rewrites)

    marker = _marker(conn)
    for dependency_id, column, old, new in rewrites:
        conn.execute(
            f"UPDATE item_dependencies SET {column}={marker} WHERE id={marker}",
            (new, dependency_id),
        )
        print(f"{MIGRATION_NAME}: {dependency_id} / {column} / {old} -> {new}")


def invariants(conn: Any) -> None:
    """Require every stored ref to be a public ref or genuinely orphaned.

    Refs that resolve under neither reading are carried forward as a
    documented allowance: they name items that no longer exist, so no public
    ref can be derived for them and they are not evidence of a failed repair.
    """
    _require_tables(conn)
    rewrites, _unresolvable, _ambiguous = classify(conn)
    if rewrites:
        detail = ", ".join(
            f"{dependency_id}/{column}/{old}" for dependency_id, column, old, _ in rewrites
        )
        raise AssertionError(
            f"{MIGRATION_NAME}: {len(rewrites)} dependency refs still resolve only "
            f"as internal item ids: {detail}"
        )


__all__ = [
    "MAX_REWRITES",
    "MIGRATION_NAME",
    "REF_COLUMNS",
    "apply",
    "classify",
    "invariants",
]
