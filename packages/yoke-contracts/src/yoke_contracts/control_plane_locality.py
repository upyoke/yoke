"""Whether the active control plane can be opened directly, per execution context.

A control plane reached over https is not openable from the caller's machine:
there is no local Postgres to connect to. Code that runs there must reach
control-plane rows by relaying a function call, never by opening a connection.
Opening one anyway does not always fail loudly — one observed instance died
with a traceback, another returned ``False`` from inside a blanket ``except``
and silently skipped the write it was supposed to make.

This module carries that fact on a request-scoped ContextVar so the connection
factory can refuse the call at the moment it happens, instead of leaving each
caller to discover it. The client entrypoint marks the context once when the
active connection is https; every nested call inherits the mark, including
through engine code the client runs locally.

A ContextVar rather than an environment variable for the same reason
:mod:`yoke_contracts.hook_runner` and the done-transition claim bypass use one:
a server process relays many requests through one interpreter, and a
process-global flag set for one request leaks into every concurrent one.

Two surfaces legitimately open a local connection while the marker is set, and
both say so with :func:`local_authority_exempt` rather than being listed in an
allowlist that rots as files move:

* the local-first probe in
  :func:`yoke_core.domain.control_plane_transport.local_connection_or_none`,
  whose whole job is to try a direct connection and treat failure as the cue
  to relay;
* source-dev and operator-debug tools that hold an explicit authority DSN and
  mean to talk to that database directly.

Server-side dispatch never sets the marker at all: the server holds the
authority it is connecting to, so its handlers connect normally.
"""

from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from typing import Iterator, Mapping, Optional

#: Environment variables that pin one explicit Postgres authority. Named here
#: rather than in the connection factory because the client entrypoint has to
#: read them before it decides whether to mark the context, and it cannot
#: import the engine. ``yoke_core.domain.db_backend`` re-exports both under
#: its historical names.
PG_DSN_ENV = "YOKE_PG_DSN"
PG_DSN_FILE_ENV = "YOKE_PG_DSN_FILE"


class RemoteControlPlaneConnectionError(BaseException):
    """A direct connection was attempted where the control plane is remote.

    Deliberately outside the ``Exception`` hierarchy, the way
    :class:`KeyboardInterrupt` and :class:`SystemExit` are. One of the
    instances this guard exists to catch was a bare connection inside a
    blanket ``except Exception`` that returned ``False``: the write it was
    supposed to make never happened and nothing anywhere said so. An error
    that ordinary recovery code can swallow would have been swallowed there
    too, so this one cannot be — it is a defect in the call path, never a
    condition to recover from. Code that means to open a local database says
    so with :func:`local_authority_exempt` instead of catching this.
    """


# Request-scoped locality mark. The default False means "unmarked", which is
# the correct answer for a server process and for a machine whose control
# plane is a local Postgres — both can open the authority directly.
_remote_control_plane: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "remote_control_plane", default=False,
)


@contextmanager
def remote_control_plane() -> Iterator[None]:
    """Mark this context as running against a control plane it cannot open."""
    token = _remote_control_plane.set(True)
    try:
        yield
    finally:
        _remote_control_plane.reset(token)


@contextmanager
def local_authority_exempt() -> Iterator[None]:
    """Declare that this block opens a local database on purpose.

    Clears the locality mark for the duration, so the connection factory
    admits the call. Use it where a direct connection is the intent — the
    local-first relay probe, and source-dev / operator-debug tools that carry
    their own authority DSN — and nowhere else. The block is the declaration:
    it is what both the runtime guard and the static scan read, so a legitimate
    exception stays visible at the call site instead of in a separate list.
    """
    token = _remote_control_plane.set(False)
    try:
        yield
    finally:
        _remote_control_plane.reset(token)


def remote_control_plane_active() -> bool:
    """Return whether this context runs against a control plane it cannot open."""
    return _remote_control_plane.get()


def local_authority_is_pinned(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return whether an explicit Postgres authority is pinned in *env*.

    A pin means a database to open is named outright, so it settles the
    locality question before any connection config is consulted — the same
    order the DSN resolver already uses.
    """
    source = os.environ if env is None else env
    return any(source.get(name) for name in (PG_DSN_ENV, PG_DSN_FILE_ENV))


def refuse_direct_connection(operation: str) -> None:
    """Raise when *operation* would open a connection the caller cannot open.

    A no-op in every unmarked context, so the check costs one ContextVar read
    on the normal path.
    """
    if not _remote_control_plane.get():
        return
    raise RemoteControlPlaneConnectionError(
        f"{operation} cannot open the active control plane: it is reached over "
        "https, so there is no local database to connect to. Reach "
        "control-plane rows through the function-call relay "
        "(yoke_core.domain.control_plane_transport.relay) instead of opening a "
        "connection. If this call really does mean to open a local database "
        "it holds authority over, wrap it in "
        "yoke_contracts.control_plane_locality.local_authority_exempt()."
    )


__all__ = [
    "PG_DSN_ENV",
    "PG_DSN_FILE_ENV",
    "RemoteControlPlaneConnectionError",
    "local_authority_exempt",
    "local_authority_is_pinned",
    "refuse_direct_connection",
    "remote_control_plane",
    "remote_control_plane_active",
]
