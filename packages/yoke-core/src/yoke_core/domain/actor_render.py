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
from typing import Any, Optional

from yoke_core.domain.actors import ActorError, actor_name


def _is_line_safe(char: str) -> bool:
    """Whether ``char`` can appear inside one rendered line."""
    return unicodedata.category(char) not in ("Cc", "Cf", "Zl", "Zp")


_WHITESPACE_RUN = re.compile(r"\s+")


def render_actor_name(conn: Any, actor_id: Optional[int]) -> Optional[str]:
    """One-line display name for ``actor_id``, or ``None`` if unresolvable.

    Never raises (fail-open): a null id, a nonexistent actor, or an actor
    with no name at all yields ``None`` so the caller can omit the field
    ("print the name only if we have it"). Interior spaces survive;
    control characters, newlines, and repeated whitespace collapse to a
    single space so the result occupies exactly one line.
    """
    if actor_id is None:
        return None
    try:
        name = actor_name(conn, int(actor_id))
    except (ActorError, TypeError, ValueError):
        return None
    safe = "".join(char if _is_line_safe(char) else " " for char in name)
    return _WHITESPACE_RUN.sub(" ", safe).strip() or None


__all__ = ["render_actor_name"]
