"""Fail-open actor name rendering for operator-facing surfaces.

A render adapter over :func:`yoke_core.domain.actors.actor_name`. The
lower-level helper is fail-closed because a caller that holds an id and
asks for a name is usually about to write it somewhere durable. A view
has the opposite need: it must never fail to render because an editor's
actor row is missing, so this returns ``None`` and the caller omits the
field.

Rendering preserves spaces. A person's name is "Ada Lovelace", not
"Ada-Lovelace", and the surfaces that read this — session-message
framing, claim holders, session rosters — are line-oriented rather than
token-oriented. What the sanitizer removes is what would break a line:
control characters and newlines collapse to a single space, so a name
can never split one rendered record into two or forge a framing line.

The stored identity stays the numeric actor id; the name is a
render-time projection only.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.actors import ActorError, actor_name


def _is_line_safe(char: str) -> bool:
    """Whether ``char`` can appear inside one rendered line."""
    return unicodedata.category(char) not in ("Cc", "Cf", "Zl", "Zp")


_WHITESPACE_RUN = re.compile(r"\s+")


def _one_line(name: str) -> Optional[str]:
    """Collapse a stored name to exactly one renderable line, or ``None``."""
    safe = "".join(char if _is_line_safe(char) else " " for char in name)
    return _WHITESPACE_RUN.sub(" ", safe).strip() or None


def render_actor_name(conn: Any, actor_id: Optional[int]) -> Optional[str]:
    """One-line display name for ``actor_id``, or ``None`` if unresolvable.

    Never raises (fail-open): a null id, a nonexistent actor, or an actor
    with no name at all yields ``None`` so the caller can omit the field
    ("print the name only if we have it"). Interior spaces survive;
    control characters, newlines, and repeated whitespace collapse to a
    single space so the result occupies exactly one line.

    The one-element case of :func:`render_actor_names`; a caller rendering
    a page of rows uses the batch entry point so the read stays one
    statement instead of one per row.
    """
    if actor_id is None:
        return None
    try:
        name = actor_name(conn, int(actor_id))
    except (ActorError, TypeError, ValueError):
        return None
    return _one_line(name)


def _stored_names(conn: Any, actor_ids: Iterable[Any]) -> dict[int, str]:
    """Stored names for a set of ids, in one statement; absent ids are absent.

    Every display-side reader here needs the same set read, so it lives in
    one place: a page naming its actors costs one query for the distinct
    actors on it, never one per row that mentions one.
    """
    ids: list[int] = []
    for value in dict.fromkeys(actor_ids):
        if value is None:
            continue
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT id, name FROM actors WHERE id IN ("
        + ", ".join(marker for _ in ids)
        + ")",
        tuple(ids),
    ).fetchall()
    return {int(row[0]): str(row[1] or "") for row in rows}


def render_actor_names(
    conn: Any,
    actor_ids: Iterable[Any],
) -> dict[int, Optional[str]]:
    """Display names for a whole set of actor ids, in one statement.

    Same fail-open contract per id as :func:`render_actor_name`: an id with
    no actor row, or one whose name is empty, maps to ``None`` so the caller
    omits the field for that row.
    """
    return {
        actor_id: _one_line(name)
        for actor_id, name in _stored_names(conn, actor_ids).items()
    }


def actor_display_labels(
    conn: Any,
    actor_ids: Iterable[int],
) -> dict[int, str]:
    """Render actor ids distinctly when two actors share one name.

    Unlike :func:`render_actor_names` this always renders something: an id
    with no actor row, or one whose stored name is empty, reads as
    ``actor N`` rather than disappearing, because the callers are naming a
    decider or an approver whose absence from the sentence would change what
    it says.
    """
    ids = tuple(sorted({int(value) for value in actor_ids}))
    if not ids:
        return {}
    names = _stored_names(conn, ids)
    labels = {
        actor_id: (names.get(actor_id) or "").strip() or f"actor {actor_id}"
        for actor_id in ids
    }
    values = tuple(labels.values())
    counts = {label: values.count(label) for label in values}
    return {
        actor_id: label if counts[label] == 1 else f"{label} (actor {actor_id})"
        for actor_id, label in labels.items()
    }


__all__ = ["actor_display_labels", "render_actor_name", "render_actor_names"]
