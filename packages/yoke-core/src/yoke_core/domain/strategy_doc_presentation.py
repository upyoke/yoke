"""Display projections derived from DB-authoritative strategy documents."""

from __future__ import annotations

from typing import Any


def title_from_content(slug: str, content: str) -> str:
    """Return the first Markdown H1, with a readable slug fallback."""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return slug.replace("-", " ").replace("_", " ").title()


def summary_from_row(conn: Any, row: Any) -> dict[str, object]:
    """Project a strategy-doc database row for list displays."""
    from yoke_core.domain.actor_render import actor_render_label

    slug = str(row["slug"])
    content = str(row["content"])
    return {
        "slug": slug,
        "title": title_from_content(slug, content),
        "updated_at": str(row["updated_at"]),
        "updated_by": actor_render_label(conn, row["updated_by_actor_id"]),
        "bytes": len(content.encode("utf-8")),
        "archived": row["archived_at"] is not None,
    }


__all__ = ["summary_from_row", "title_from_content"]
