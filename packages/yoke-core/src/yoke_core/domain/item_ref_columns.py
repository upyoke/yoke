"""Canonical translation for DB columns that store an item ref as text.

``item_dependencies.dependent_item`` and ``item_dependencies.blocking_item``
key on the **public** item ref — ``{projects.public_item_prefix}-{items
.project_sequence}`` — rather than the internal global ``items.id``. Once a
project's sequence diverges from the internal id the two readings name
different items, and a hardcoded prefix names the wrong project outright.
So every writer renders the ref from the item's own project, and every
reader resolves it back through prefix + sequence.

This module owns both directions:

* :func:`render_column_item_ref` turns any item token (internal id, bare
  digit string, or public ref) into the canonical stored ref, carrying the
  resolved item's OWN project prefix.
* :func:`resolve_column_item_ref` turns a stored ref back into the internal
  ``items.id``, or ``None`` when it names no item. ``None`` is the
  fail-safe answer: a gate reading ``None`` on the blocking side keeps
  reporting blocked rather than silently resolving to the wrong item.
* :func:`column_item_id_sql` is the same resolution as a SQL scalar
  expression, for join sites that must resolve the ref inside a single
  query. On a schema without the project tables/columns (minimal in-memory
  fixtures) it degrades to the numeric-tail reading so those callers keep
  working.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import render_item_ref

_PROBE_SQL = (
    "SELECT rp.public_item_prefix, ri.project_sequence "
    "FROM items ri JOIN projects rp ON rp.id = ri.project_id WHERE 1 = 0"
)

# The characters after the prefix separator, or the whole value when it
# carries no separator. ``POSITION`` / ``INSTR`` answer 0 for "not found", so
# the offset arithmetic lands on character 1 and bare ids fall out for free.
_TAIL_POSTGRES_SQL = "SUBSTRING({column} FROM POSITION('-' IN {column}) + 1)"
_TAIL_SQLITE_SQL = "SUBSTR({column}, INSTR({column}, '-') + 1)"

# Canonical prefix + project_sequence match first; the numeric tail read as an
# internal id is the fallback, mirroring :func:`render_column_item_ref`. Order
# matters — when a ref's sequence reading and its id reading both name a (
# different) row, the sequence reading is the contract.
_PUBLIC_REF_SQL = (
    "COALESCE("
    "(SELECT ri.id FROM items ri JOIN projects rp ON rp.id = ri.project_id "
    "WHERE UPPER(rp.public_item_prefix) || '-' "
    "|| CAST(ri.project_sequence AS TEXT) = UPPER({column})), "
    "(SELECT rt.id FROM items rt WHERE CAST(rt.id AS TEXT) = {tail}))"
)


def _supports_public_refs(conn: Any) -> bool:
    """True when the schema carries the project tables the ref join needs."""
    use_savepoint = db_backend.connection_is_postgres(conn)
    savepoint = "_yoke_item_ref_column_probe"
    try:
        if use_savepoint:
            conn.execute(f"SAVEPOINT {savepoint}")
        conn.execute(_PROBE_SQL).fetchall()
        if use_savepoint:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return True
    except Exception:  # noqa: BLE001 - any schema shortfall means "no"
        if use_savepoint:
            try:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:  # noqa: BLE001
                pass
        return False


def _numeric_tail(value: Any) -> Optional[int]:
    text = str(value).strip().rsplit("-", 1)[-1]
    if not text.isdigit():
        return None
    return int(text.lstrip("0") or "0")


def resolve_column_item_ref(conn: Any, value: Any) -> Optional[int]:
    """Resolve a stored item ref to the internal ``items.id``.

    Returns ``None`` when the ref names no item, so callers can skip or
    report the dangling row instead of attributing it to a wrong item. On
    a schema without the project tables the numeric tail is the only
    reading available, matching :func:`column_item_id_sql`.
    """
    if not _supports_public_refs(conn):
        return _numeric_tail(value)
    from yoke_core.domain.yok_n_parser import parse_item_id_or_none

    return parse_item_id_or_none(value, conn=conn, allow_bare_internal=True)


def render_column_item_ref(conn: Any, value: Any) -> str:
    """Render the canonical stored ref for an item token.

    Accepts an internal ``items.id`` int, a bare digit string (internal
    id), or a public ``PREFIX-N`` ref. The result always carries the
    resolved item's own project prefix — an item in another project
    renders that project's prefix rather than the caller's.

    A token the public-ref lookup cannot answer falls back to reading its
    numeric tail as an internal id before rendering. That keeps refs
    written before per-project sequences existed pointing at the item
    their author meant, and leaves refs with no backing row rendering the
    same text they carried on disk.
    """
    item_id = resolve_column_item_ref(conn, value)
    if item_id is None:
        item_id = _numeric_tail(value)
    if item_id is None:
        return str(value).strip().upper()
    return render_item_ref(conn, item_id)


def column_item_id_sql(conn: Any, column: str) -> str:
    """SQL scalar expression resolving a ref column to ``items.id``.

    ``column`` is the qualified column reference to translate (e.g.
    ``d.blocking_item``). The expression yields ``NULL`` for a ref that
    names no item, so a ``LEFT JOIN`` through it leaves the counterpart's
    columns NULL and satisfaction evaluation keeps the edge unsatisfied.
    """
    tail_template = (
        _TAIL_POSTGRES_SQL
        if db_backend.connection_is_postgres(conn)
        else _TAIL_SQLITE_SQL
    )
    tail = tail_template.format(column=column)
    if _supports_public_refs(conn):
        return _PUBLIC_REF_SQL.format(column=column, tail=tail)
    return f"CAST({tail} AS INTEGER)"


__all__ = [
    "column_item_id_sql",
    "render_column_item_ref",
    "resolve_column_item_ref",
]
