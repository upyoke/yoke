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


#: The closed vocabulary for ``## State``. Nothing computes it: a shelved plan
#: and an active one look identical to every query you could run, so the author
#: declares it. Closed so the ingest can reject a fifth.
DOC_STATES = frozenset({"active", "locked", "deferred", "reference"})

#: A card renders the summary whole, which is what makes a per-view
#: summarising call unnecessary; a bounded field needs no model to shorten it.
SUMMARY_MAX_CHARS = 200


def _heading_body(content: str, heading: str) -> str:
    """Return the text under ``## heading``, up to the next heading."""
    wanted = f"## {heading}".casefold()
    collected: list[str] = []
    inside = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            if inside:
                break
            inside = line.casefold() == wanted
            continue
        if inside and line:
            collected.append(line)
    return " ".join(collected).strip()


def summary_from_content(content: str) -> str | None:
    """Return the document's own one-sentence summary, or None.

    The summary is authored, not derived: a card cannot show a 190KB document,
    and asking a model to shorten one on every render is a per-view call that
    drifts from the document it summarises. A document with no such heading
    reports None so the reader can say which heading is missing, rather than
    rendering blank — a blank card reads as a rendering fault, which is the one
    thing that state is not.
    """
    body = _heading_body(content, "Summary")
    return body[:SUMMARY_MAX_CHARS] if body else None


def state_from_content(content: str) -> str | None:
    """Return the declared ``## State``, or None when absent or unknown."""
    body = _heading_body(content, "State").casefold()
    first = body.split()[0].strip(".,;:") if body else ""
    return first if first in DOC_STATES else None


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
        "summary": summary_from_content(content),
        "state": state_from_content(content),
    }


__all__ = [
    "DOC_STATES",
    "SUMMARY_MAX_CHARS",
    "state_from_content",
    "summary_from_content",
    "summary_from_row",
    "title_from_content",
]
