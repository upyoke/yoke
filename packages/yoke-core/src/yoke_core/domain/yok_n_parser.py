"""Shared item-argument parser over the one item-identity resolver.

Text tokens resolve through
:func:`yoke_core.domain.item_ref_resolution.resolve_item_ref`: ``PREFIX-N``
resolves through its unique ``projects.public_item_prefix`` plus
``items.project_sequence``. Text arguments require that complete public ref;
project context scopes the request without supplying a missing prefix.
A Python ``int`` is an internal id an engine caller already holds and passes
through. This module adds the open path: a caller with no connection of its
own resolves over a direct local connection, or through the dispatcher when
the connected control plane is one the client cannot open.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Union

from yoke_core.domain import control_plane_transport
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.item_ref_resolution import (
    ItemRefError,
    check_item_ref_shape,
    resolve_item_ref,
)


#: The item-targeted read whose target resolution answers the same question:
#: the dispatcher turns a public ref into an internal id before the handler
#: runs, and returns the canonical public ref on the item it read.
RESOLVE_FUNCTION_ID = "items.detail.get"


def parse_item_id(
    value: Union[str, int, None],
    *,
    project: str | int | None = None,
    conn: Any | None = None,
) -> int | str:
    """Resolve onto a local join key, or retain the public ref over HTTPS.

    Raises :class:`ItemRefError` (a ``ValueError``) naming the fix when the
    token names no single item.
    """
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    check_item_ref_shape(value, project=project)
    return _resolve_over_open_path(value.strip(), project=project, conn=conn)


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
) -> int | str:
    """Resolve one operator-facing item argument through public identity."""
    return parse_item_id(
        value,
        project=item_argument_project(project, cwd=cwd),
        conn=conn,
    )


def _resolve_over_open_path(
    text: str,
    *,
    project: str | int | None,
    conn: Any | None,
) -> int | str:
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
    conn: Any,
    text: str,
    *,
    project: str | int | None,
) -> int | str:
    return resolve_item_ref(conn, text, project=project)


def _resolve_over_relay(text: str, *, project: str | int | None) -> str:
    """Validate the item on the server and keep its public identity client-side."""
    from yoke_contracts.api.function_call import TargetRef

    target = TargetRef(
        kind="item",
        public_ref=text,
        project_id=None if project is None else str(project),
    )
    try:
        result = control_plane_transport.relay(RESOLVE_FUNCTION_ID, {}, target)
    except RuntimeError as exc:
        raise ItemRefError("item_ref_unresolved", str(exc)) from exc
    item = result.get("item") or {}
    resolved = item.get("public_ref")
    if resolved is None:
        raise ItemRefError("item_ref_unresolved", f"item ref {text!r} not found")
    return str(resolved)


def parse_item_id_or_none(
    value: Union[str, int, None],
    *,
    project: str | int | None = None,
    conn: Any | None = None,
) -> int | None:
    """:func:`parse_item_id` returning ``None`` instead of raising.

    For gate/audit surfaces that skip or report unparseable refs rather
    than aborting.
    """
    try:
        return parse_item_id(value, project=project, conn=conn)
    except ValueError:
        return None


__all__ = [
    "item_argument_project",
    "parse_item_argument",
    "parse_item_id",
    "parse_item_id_or_none",
]
