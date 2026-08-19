"""Rendering internal ``items.id`` values into public item refs.

A public ref is project-scoped (``projects.public_item_prefix`` +
``items.project_sequence``), so rendering one always needs a row read. Any
surface that renders a *set* of refs — offer diagnostics, the frontier-state
projection, a drift-review delta — reads that set in one statement through
:func:`render_item_refs` rather than one statement per element. The
single-id :func:`yoke_core.domain.project_identity.render_item_ref` is the
one-element case of the same projection.

Rows that resolve to no item (or a schema with no ``projects`` table) fall
back to ``{DEFAULT_PUBLIC_ITEM_PREFIX}-{id}``, matching the single-id
renderer.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from yoke_contracts.item_ref import DEFAULT_PUBLIC_ITEM_PREFIX, format_item_ref

from yoke_core.domain.db_backend import connection_is_postgres

ITEM_REF_PROJECTION_SQL = """
SELECT i.id AS id, p.slug AS slug, p.public_item_prefix AS public_item_prefix,
       i.project_sequence AS project_sequence
FROM items i
JOIN projects p ON p.id = i.project_id
WHERE i.id IN ({placeholders})
"""


def fallback_item_ref(item_id: int) -> str:
    """Return the ref used when no identity row backs ``item_id``."""
    return f"{DEFAULT_PUBLIC_ITEM_PREFIX}-{item_id}"


def _row_value(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (TypeError, IndexError, KeyError):
        return row[index]


def _distinct_ids(item_ids: Iterable[Any]) -> List[int]:
    """Coerce caller ids to a de-duplicated, order-preserving int list."""
    ordered: List[int] = []
    seen: set[int] = set()
    for raw in item_ids:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def fetch_item_ref_rows(conn: Any, sql: str, params: Sequence[Any]) -> List[Any]:
    """Fetch ref-projection rows, tolerating a schema without the project
    tables/columns (e.g. doctor HCs on bare/legacy schemas). A savepoint (when
    the backend supports one) keeps the connection usable if the read raises;
    returns an empty list so callers emit the prefix+id fallback.
    """
    transaction = getattr(conn, "transaction", None)
    if callable(transaction):
        try:
            with transaction():
                return list(conn.execute(sql, tuple(params)).fetchall())
        except Exception:
            return []
    try:
        return list(conn.execute(sql, tuple(params)).fetchall())
    except Exception:
        return []


def render_item_refs(
    conn: Any,
    item_ids: Iterable[Any],
) -> Dict[int, str]:
    """Map the internal ids that have an identity row to their public refs.

    Ids with no backing row are absent from the result rather than carrying a
    fallback, so a caller that needs to distinguish "no such item" still can.
    :class:`ItemRefLookup` applies the fallback for rendering callers.
    """
    ids = _distinct_ids(item_ids)
    if not ids or conn is None:
        return {}
    marker = "%s" if connection_is_postgres(conn) else "?"
    sql = ITEM_REF_PROJECTION_SQL.format(
        placeholders=", ".join(marker for _ in ids)
    )
    refs: Dict[int, str] = {}
    for row in fetch_item_ref_rows(conn, sql, ids):
        item_id = int(_row_value(row, "id", 0))
        refs[item_id] = format_item_ref(
            _row_value(row, "slug", 1),
            _row_value(row, "public_item_prefix", 2),
            _row_value(row, "project_sequence", 3),
            item_id=item_id,
        )
    return refs


def render_item_ref_lookup(
    conn: Any,
    item_ids: Iterable[Any],
) -> "ItemRefLookup":
    """Resolve ``item_ids`` once and return a reusable renderer for them."""
    return ItemRefLookup(render_item_refs(conn, item_ids), consulted=conn is not None)


class ItemRefLookup:
    """A resolved id -> public-ref map, rendering ids it could not resolve.

    Callers that fan a pre-resolved set out across several projections hold
    one of these instead of a connection, which makes an accidental
    one-query-per-item render impossible to write.

    ``consulted`` records whether a database was available to answer at all,
    because the two unresolved cases mean different things: an id with no
    identity row renders as the prefix+id fallback, while a caller with no
    connection renders the bare internal id — a public-looking ref from a
    lookup that never happened would be wrong for any item whose project
    sequence diverges from its internal id.
    """

    __slots__ = ("_refs", "_consulted")

    def __init__(
        self,
        refs: Optional[Dict[int, str]] = None,
        *,
        consulted: bool = True,
    ) -> None:
        self._refs = dict(refs or {})
        self._consulted = consulted

    def __call__(self, item_id: Any) -> str:
        try:
            value = int(item_id)
        except (TypeError, ValueError):
            return str(item_id)
        rendered = self._refs.get(value)
        if rendered:
            return rendered
        return fallback_item_ref(value) if self._consulted else str(value)


__all__ = [
    "ITEM_REF_PROJECTION_SQL",
    "ItemRefLookup",
    "fallback_item_ref",
    "fetch_item_ref_rows",
    "render_item_ref_lookup",
    "render_item_refs",
]
