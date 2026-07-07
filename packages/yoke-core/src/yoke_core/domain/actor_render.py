"""Fail-open actor display rendering.

A render adapter over :func:`yoke_core.domain.actors.actor_display_name`.
The lower-level actor helpers are fail-closed because GitHub sync and other
external projections must not emit malformed tokens. Display rendering has
the opposite need: a view must never fail to render because an editor's
identity has no label yet, so this returns ``None`` and the caller omits the
field.

The stored identity stays the numeric actor id; the label is a render-time
projection only. When a richer identity layer (e.g. a users table) maps
``actor_id`` to a person, the same id resolves to a better label with no
change to stored data.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from yoke_core.domain.actor_display import actor_display_name
from yoke_core.domain.actors import (
    ActorError,
    actor_label,
)

# Render headers/labels are space-delimited tokens, so a rendered label must
# be a single token; collapse anything outside this charset to '-'.
_UNSAFE_LABEL_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def actor_render_label(
    conn: Any,
    actor_id: Optional[int],
    *,
    surface: Optional[str] = None,
) -> Optional[str]:
    """Single-token display label for ``actor_id``, or ``None`` if unresolvable.

    Never raises (fail-open): a null id, an unlabeled actor, an ambiguous
    mapping, or a nonexistent actor all yield ``None`` so the caller can omit
    the field ("print the label only if we have it"). The result is sanitized
    to one ``[A-Za-z0-9._-]`` token, safe to embed in a space-delimited
    render header.
    """
    if actor_id is None:
        return None
    try:
        if surface is None:
            label = actor_display_name(conn, int(actor_id))
        else:
            label = actor_label(conn, int(actor_id), surface=surface)
    except ActorError:
        return None
    token = _UNSAFE_LABEL_CHARS.sub("-", label.strip())
    return token or None


__all__ = ["actor_render_label"]
