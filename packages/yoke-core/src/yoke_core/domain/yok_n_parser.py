"""Shared item-reference parser.

Python integers are internal ``items.id`` values. Public refs such as
``YOK-N`` resolve through a unique ``projects.public_item_prefix`` plus
``items.project_sequence``. String digits are project-local sequence refs when
project context is known. Direct Python integer values are internal
``items.id`` values. String digits without project context are rejected unless
an internal/debug caller explicitly opts into ``allow_bare_internal``.
"""

from __future__ import annotations

import re
from typing import Any, Union

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_identity import resolve_item_id


_PUBLIC_REF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")


_TEACHING_MESSAGE = (
    "invalid item ref: {value!r}; expected PREFIX-N, or bare N with "
    "project context"
)
_BARE_CONTEXT_MESSAGE = (
    "bare numeric item refs are project-local; run inside a registered "
    "project checkout or pass --project <slug>"
)
_SLASH_MESSAGE = (
    "project-qualified item refs are retired; use PREFIX-N, or bare N "
    "with --project <slug>"
)
_NOT_FOUND_MESSAGE = "item ref {value!r} not found"


def parse_item_id(
    value: Union[str, int, None],
    *,
    project: str | int | None = None,
    conn: Any | None = None,
    allow_bare_internal: bool = False,
) -> int:
    """Resolve an item token to the internal global ``items.id``."""
    if isinstance(value, bool):
        # bool is a subclass of int; rejected to avoid surprise.
        raise ValueError(_TEACHING_MESSAGE.format(value=value))
    if isinstance(value, int):
        if value < 0:
            raise ValueError(_TEACHING_MESSAGE.format(value=value))
        return value
    if value is None:
        raise ValueError(_TEACHING_MESSAGE.format(value=value))
    text = str(value).strip()
    if not text:
        raise ValueError(_TEACHING_MESSAGE.format(value=value))
    if "/" in text:
        raise ValueError(_SLASH_MESSAGE)
    if text.isdigit() and project is None:
        if not allow_bare_internal:
            raise ValueError(_BARE_CONTEXT_MESSAGE)
        cleaned = text.lstrip("0") or "0"
        return int(cleaned)
    if text.isdigit() or _PUBLIC_REF_RE.match(text):
        owns_conn = conn is None
        db_conn = conn or connect()
        try:
            try:
                resolved = resolve_item_id(db_conn, text, project=project)
            except LookupError as exc:
                raise ValueError(str(exc)) from exc
        finally:
            if owns_conn:
                db_conn.close()
        if resolved is None:
            raise ValueError(_NOT_FOUND_MESSAGE.format(value=value))
        return resolved
    raise ValueError(_TEACHING_MESSAGE.format(value=value))


__all__ = ["parse_item_id"]
