"""Translate API item tokens to and from the public PREFIX-N form.

Storage for ``item_dependencies`` is integer ``items.id`` foreign keys.
Callers that accept a public ref, bare id, or mixed token use
:func:`resolve_column_item_ref` on the way in and
:func:`render_column_item_ref` on the way out to the API or display.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import render_item_ref

_PROBE_SQL = (
    "SELECT rp.public_item_prefix, ri.project_sequence "
    "FROM items ri JOIN projects rp ON rp.id = ri.project_id WHERE 1 = 0"
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
    """Resolve an API item token to the internal ``items.id``.

    Returns ``None`` when the token names no item. On a schema without
    the project tables the numeric tail is the only reading available.
    """
    if isinstance(value, int):
        return value
    if not _supports_public_refs(conn):
        return _numeric_tail(value)
    from yoke_core.domain.yok_n_parser import parse_item_id_or_none

    # This exact compatibility reader consumes a legacy textual storage column,
    # not an operator argument; digit strings in that column are internal ids.
    return parse_item_id_or_none(
        value, conn=conn, allow_bare_internal=True,
    )


def render_column_item_ref(conn: Any, value: Any) -> str:
    """Render the canonical public ref for an item token.

    Accepts an internal ``items.id`` int, a bare digit string, or a
    public ``PREFIX-N`` ref. The result always carries the resolved
    item's own project prefix.

    A token the public-ref lookup cannot answer falls back to reading
    its numeric tail as an internal id before rendering. A token with
    no backing row renders the same text it arrived with.
    """
    item_id = resolve_column_item_ref(conn, value)
    if item_id is None:
        item_id = _numeric_tail(value)
    if item_id is None:
        return str(value).strip().upper()
    return render_item_ref(conn, item_id)


__all__ = [
    "render_column_item_ref",
    "resolve_column_item_ref",
]
