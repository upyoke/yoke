"""Render the ``## Block`` body section when ``items.blocked = 1``.

The blocked-flag retirement chose flag semantics over status semantics for item-level blocking.
The board, frontier, and scheduler render the routing/display state from the
flag; the rendered body surfaces the operator-supplied reason and the time
at which the block was last touched so the item-detail view is diagnostic
without forcing the reader back to the events table.

This module is a single responsibility — composing the section. The render
order in :mod:`yoke_core.domain.render_body` calls this helper after the
normal Spec / Design Spec / DB Claim / Path Claims / Technical Plan / etc.
chunks so the block appears as a clear top-of-detail signal.

Note: ``items.blocked`` is unrelated to ``path_claims.state='blocked'``;
the latter is a coordination state on a single path-claim row, surfaced
in the rendered Path Claims section, not here.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.queries import is_blocked
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns


_HEADING = "## Block"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def render_blocked_section(conn: Any, item_id: int) -> Optional[str]:
    """Return the rendered ``## Block`` section, or None when not blocked.

    The section is only emitted when ``items.blocked = 1``. The body names
    the operator-supplied ``blocked_reason`` (when present) plus the
    ``updated_at`` timestamp on the items row — the time of the last
    blocked-state mutation. Both are best-effort: missing reason or
    missing timestamp degrade gracefully to a single-line section.
    """
    available = set(_schema_get_columns(conn, "items"))
    if "blocked" not in available:
        return None

    cols = ["blocked"]
    if "blocked_reason" in available:
        cols.append("blocked_reason")
    if "updated_at" in available:
        cols.append("updated_at")
    p = _p(conn)
    row = conn.execute(
        f"SELECT {', '.join(cols)} FROM items WHERE id = {p}",
        (item_id,),
    ).fetchone()
    if row is None:
        return None

    if not is_blocked(row[0]):
        return None

    reason = row[1] if len(row) > 1 else None
    updated_at = row[2] if len(row) > 2 else None

    lines = [_HEADING, ""]
    if reason and str(reason).strip():
        lines.append(f"**Reason:** {str(reason).strip()}")
    else:
        lines.append("**Reason:** (none recorded)")
    if updated_at:
        lines.append(f"**Last updated:** {updated_at}")
    lines.append(
        "Unblock with `/yoke unblock YOK-{}` once the underlying coordination "
        "is resolved.".format(item_id)
    )
    return "\n".join(lines)


__all__ = ["render_blocked_section"]
