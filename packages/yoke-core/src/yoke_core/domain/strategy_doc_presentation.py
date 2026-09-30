"""Display projections derived from DB-authoritative strategy documents."""

from __future__ import annotations

from typing import Any

from yoke_contracts.project_contract.strategy_doc_fields import (
    SUMMARY_MAX_CHARS,
    read_field,
)


def title_from_content(slug: str, content: str) -> str:
    """Return the first Markdown H1, with a readable slug fallback."""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return slug.replace("-", " ").replace("_", " ").title()


def summary_from_content(content: str) -> str | None:
    """Return the document's own one-sentence summary, or None.

    The summary is authored, not derived: a card cannot show a 190KB document,
    and asking a model to shorten one on every render is a per-view call that
    drifts from the document it summarises. A document with no such heading
    reports None so the reader can say which heading is missing, rather than
    rendering blank — a blank card reads as a rendering fault, which is the one
    thing that state is not.
    """
    body = read_field(content, "Summary")
    return body[:SUMMARY_MAX_CHARS] if body else None


def state_from_content(content: str) -> str | None:
    """Return the authored State text, preserving spelling and case."""
    return read_field(content, "State")


def summary_from_row(conn: Any, row: Any) -> dict[str, object]:
    """Project a strategy-doc database row for list displays."""
    from yoke_core.domain.actor_render import render_actor_name

    slug = str(row["slug"])
    content = str(row["content"])
    return {
        "slug": slug,
        "title": title_from_content(slug, content),
        "updated_at": str(row["updated_at"]),
        "updated_by": render_actor_name(conn, row["updated_by_actor_id"]),
        "bytes": len(content.encode("utf-8")),
        "archived": row["archived_at"] is not None,
        "summary": summary_from_content(content),
        "state": state_from_content(content),
    }


__all__ = [
    "SUMMARY_MAX_CHARS",
    "state_from_content",
    "summary_from_content",
    "summary_from_row",
    "title_from_content",
]
