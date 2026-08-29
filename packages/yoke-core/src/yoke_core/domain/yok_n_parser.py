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
from pathlib import Path
from typing import Any, Union

from yoke_core.domain import control_plane_transport
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_identity import resolve_item_id


_PUBLIC_REF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")

#: The item-targeted read whose target resolution answers the same question:
#: the dispatcher turns a public ref into an internal id before the handler
#: runs, and returns that id on the item it read.
RESOLVE_FUNCTION_ID = "items.detail.get"


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
        resolved = _resolve_over_open_path(text, project=project, conn=conn)
        if resolved is None:
            raise ValueError(_NOT_FOUND_MESSAGE.format(value=value))
        return resolved
    raise ValueError(_TEACHING_MESSAGE.format(value=value))


def item_argument_project(
    explicit: str | int | None = None,
    *,
    cwd: str | Path | None = None,
) -> str | int | None:
    """Return the project context for an operator-facing item argument.

    Explicit context wins. Otherwise only the registered checkout containing
    *cwd* may supply context; installed-project and session-item guessing are
    intentionally excluded.
    """
    if explicit is not None:
        return explicit
    from yoke_core.domain import machine_config

    return machine_config.project_id(Path.cwd() if cwd is None else Path(cwd))


def parse_item_argument(
    value: Union[str, int, None],
    *,
    project: str | int | None = None,
    conn: Any | None = None,
    cwd: str | Path | None = None,
) -> int:
    """Resolve one operator-facing item argument through public identity."""
    return parse_item_id(
        value,
        project=item_argument_project(project, cwd=cwd),
        conn=conn,
        allow_bare_internal=False,
    )


def _resolve_over_open_path(
    text: str,
    *,
    project: str | int | None,
    conn: Any | None,
) -> int | None:
    """Resolve *text* to an internal id over whichever path is open.

    A caller-supplied connection is used as-is. Otherwise a direct local
    connection is preferred, and resolution relays through the dispatcher
    when the connected control plane is one the client cannot open. Public
    refs are the reference shape every client surface accepts, so resolving
    them must not require a database the client does not have.
    """
    if conn is not None:
        return _resolve_over_connection(conn, text, project=project)
    local = control_plane_transport.local_connection_or_none(connect)
    if local is None:
        return _resolve_over_relay(text, project=project)
    try:
        return _resolve_over_connection(local, text, project=project)
    finally:
        local.close()


def _resolve_over_connection(
    conn: Any, text: str, *, project: str | int | None,
) -> int | None:
    try:
        return resolve_item_id(conn, text, project=project)
    except LookupError as exc:
        raise ValueError(str(exc)) from exc


def _resolve_over_relay(text: str, *, project: str | int | None) -> int | None:
    """Read the internal id back from the server's own ref resolution."""
    from yoke_contracts.api.function_call import TargetRef

    target = TargetRef(
        kind="item",
        public_ref=text,
        project_id=None if project is None else str(project),
    )
    try:
        result = control_plane_transport.relay(RESOLVE_FUNCTION_ID, {}, target)
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc
    item = result.get("item") or {}
    resolved = item.get("id")
    return None if resolved is None else int(resolved)


def parse_item_id_or_none(
    value: Union[str, int, None],
    *,
    project: str | int | None = None,
    conn: Any | None = None,
    allow_bare_internal: bool = False,
) -> int | None:
    """:func:`parse_item_id` returning ``None`` instead of raising.

    For gate/audit surfaces that skip or report unparseable refs rather
    than aborting.
    """
    try:
        return parse_item_id(
            value,
            project=project,
            conn=conn,
            allow_bare_internal=allow_bare_internal,
        )
    except ValueError:
        return None


__all__ = [
    "item_argument_project",
    "parse_item_argument",
    "parse_item_id",
    "parse_item_id_or_none",
]
