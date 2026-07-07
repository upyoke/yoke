"""Board SQL helpers for project-scoped reads.

Every helper here goes through the BoardDBLike query seam (``query`` /
``scalar`` / ``query_quiet``) — never the raw connection. The board's
data layer records and replays results at that seam, so a direct
``db._conn`` reach-around would bypass the recorded board data and
break https-fed renders.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Tuple

from yoke_contracts.item_ref import (
    DEFAULT_PUBLIC_ITEM_PREFIX,
    format_item_ref,
)

_VISIBLE_PROJECT_IDS: ContextVar[tuple[int, ...] | None] = ContextVar(
    "board_visible_project_ids",
    default=None,
)


def _column(alias: str, name: str) -> str:
    return f"{alias}.{name}" if alias else name


def visible_project_ids() -> tuple[int, ...] | None:
    """Return the active authenticated project visibility, if any."""
    return _VISIBLE_PROJECT_IDS.get()


@contextmanager
def scoped_project_visibility(project_ids: Any):
    """Temporarily bound board ``all`` reads to ``project_ids``.

    ``None`` means local/admin context and preserves the historical unfiltered
    aggregate board. An empty iterable is a real authenticated visibility set
    and deliberately compiles to ``1=0`` filters.
    """
    if project_ids is None:
        normalized = None
    else:
        normalized = tuple(sorted({int(project_id) for project_id in project_ids}))
    token = _VISIBLE_PROJECT_IDS.set(normalized)
    try:
        yield
    finally:
        _VISIBLE_PROJECT_IDS.reset(token)


def _ids_sql() -> str:
    ids = visible_project_ids()
    if ids is None:
        return ""
    if not ids:
        return "1=0"
    return ", ".join(str(project_id) for project_id in ids)


def project_id_filter(alias: str = "", *, prefix: str = "AND") -> str:
    """Return a visibility clause for a ``projects`` table alias."""
    ids_sql = _ids_sql()
    if not ids_sql:
        return ""
    col = _column(alias, "id")
    condition = "1=0" if ids_sql == "1=0" else f"{col} IN ({ids_sql})"
    return f" {prefix} {condition}"


def project_filter(scope: str, alias: str = "") -> str:
    if scope == "all":
        ids_sql = _ids_sql()
        if not ids_sql:
            return ""
        col = _column(alias, "project_id")
        if ids_sql == "1=0":
            return " AND 1=0"
        return f" AND {col} IN ({ids_sql})"
    col = _column(alias, "project_id")
    if str(scope).isdigit():
        return f" AND {col} = {int(scope)}"
    escaped = str(scope).replace("'", "''")
    ids_sql = _ids_sql()
    visible = "" if not ids_sql else (
        " AND 1=0" if ids_sql == "1=0" else f" AND id IN ({ids_sql})"
    )
    return f" AND {col} = (SELECT id FROM projects WHERE slug = '{escaped}'{visible})"


def project_ref_where(scope: str) -> Tuple[str, tuple[Any, ...]]:
    if str(scope).isdigit():
        return "id = %s", (int(scope),)
    ids = visible_project_ids()
    if ids is not None:
        if not ids:
            return "1=0", ()
        markers = ", ".join("%s" for _ in ids)
        return f"slug = %s AND id IN ({markers})", (scope, *ids)
    return "slug = %s", (scope,)


def scope_project_id(db: Any, scope: str | int) -> int:
    """Resolve a board scope (project slug or numeric id) to the project id."""
    if isinstance(scope, int) or str(scope).isdigit():
        return int(scope)
    ids = visible_project_ids()
    if ids is None:
        value = db.scalar("SELECT id FROM projects WHERE slug = %s", (str(scope),))
        if value is None:
            raise LookupError(f"project {scope!r} not found")
        return int(value)
    if not ids:
        rows = []
    else:
        markers = ", ".join("%s" for _ in ids)
        rows = db.query(
            f"SELECT id FROM projects WHERE slug = %s AND id IN ({markers})",
            (str(scope), *ids),
        )
    if not rows:
        raise LookupError(f"project {scope!r} not found")
    if len(rows) > 1:
        raise LookupError(f"project {scope!r} is ambiguous")
    return int(rows[0][0])


def item_ref(db: Any, item_id: int) -> str:
    """Render the public ``PREFIX-N`` reference for an item id."""
    rows = db.query(
        "SELECT p.slug, p.public_item_prefix, i.project_sequence "
        "FROM items i JOIN projects p ON p.id = i.project_id "
        "WHERE i.id = %s",
        (int(item_id),),
    )
    if not rows:
        return f"{DEFAULT_PUBLIC_ITEM_PREFIX}-{int(item_id)}"
    slug, prefix, sequence = rows[0]
    return format_item_ref(slug, prefix, sequence, item_id=int(item_id))


__all__ = [
    "item_ref",
    "project_filter",
    "project_id_filter",
    "project_ref_where",
    "scope_project_id",
    "scoped_project_visibility",
    "visible_project_ids",
]
