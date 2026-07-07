"""Create new DB-authoritative strategy docs.

Creation is deliberately separate from ``replace`` and ``ingest``:
there is no render-header CAS token for a row that does not exist yet,
so this path validates the slug, refuses duplicate rows, inserts once,
and lets callers re-render the corpus afterward.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain.strategy_docs import (
    STRATEGY_DOCS_TABLE,
    EmptyStrategyDocError,
    _byte_len,
    _require_valid_slug,
    next_updated_at,
)


class DuplicateStrategyDocError(ValueError):
    """Raised when a project already has the requested strategy doc slug."""


def create_doc(
    conn: Any,
    project_id: int,
    slug: str,
    content: str,
    actor_id: Optional[int],
) -> Dict[str, Any]:
    """Insert one new strategy doc row and return its byte report."""
    _require_valid_slug(slug)
    if not content or not content.strip():
        raise EmptyStrategyDocError(
            f"refusing to create strategy doc {slug!r} with empty content; "
            "strategy docs are never blanked through this surface."
        )
    existing = conn.execute(
        f"SELECT 1 FROM {STRATEGY_DOCS_TABLE} "
        "WHERE project_id = %s AND slug = %s",
        (project_id, slug),
    ).fetchone()
    if existing is not None:
        raise DuplicateStrategyDocError(
            f"project {project_id} already has strategy doc {slug!r}; "
            "use `yoke strategy doc replace` or edit the rendered file "
            "and run `yoke strategy ingest`."
        )
    updated_at = next_updated_at()
    conn.execute(
        f"INSERT INTO {STRATEGY_DOCS_TABLE} "
        "(project_id, slug, content, updated_at, updated_by_actor_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (project_id, slug, content, updated_at, actor_id),
    )
    conn.commit()
    return {
        "slug": slug,
        "new_bytes": _byte_len(content),
        "updated_at": updated_at,
    }


__all__ = ["DuplicateStrategyDocError", "create_doc"]

