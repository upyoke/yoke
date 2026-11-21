"""Mark one invocation's context when its control plane is reached over https.

The ``yoke`` router wraps every adapter in this mark, and the hook evaluator
wraps its in-process fallback in it, so engine code either one runs locally
refuses a direct database connection the caller's machine cannot have.
"""

from __future__ import annotations

import contextlib
from typing import Optional

from yoke_contracts.machine_config import reader as machine_config
from yoke_contracts.control_plane_locality import (
    local_authority_exempt,
    local_authority_is_pinned,
    remote_control_plane,
)
from yoke_contracts.machine_config.schema import TRANSPORT_HTTPS


def control_plane_is_remote(explicit_env: Optional[str]) -> bool:
    """Return whether this invocation has no local database it could open.

    An explicitly pinned DSN answers False whatever the machine config says:
    that pin IS a local authority, it already wins inside the DSN resolver,
    and a machine reached over https can still be handed one for a break-glass
    admin session. Otherwise the declared transport decides — keyed on the
    transport alone, not on a resolved relay target, because a missing token
    changes whether the relay can run, never whether a database exists to open
    instead. Any machine-config problem answers False, leaving the guard off
    and the pre-existing error for that problem to surface where it already
    does.
    """
    if local_authority_is_pinned():
        return False
    try:
        connection = machine_config.active_connection(explicit_env=explicit_env)
    except Exception:  # noqa: BLE001 - config problems are reported elsewhere
        return False
    return str(connection.get("transport") or "") == TRANSPORT_HTTPS


def control_plane_locality(explicit_env: Optional[str]):
    """Return the locality context this invocation's adapter runs under."""
    if control_plane_is_remote(explicit_env):
        return remote_control_plane()
    return contextlib.nullcontext()


def connection_locality(env: str):
    """Return the locality context for one call routed to connection *env*.

    The router marks the whole invocation from the *active* connection, but a
    call aimed at a named connection (an uninstall asking the connection that
    owns a checkout) runs against that connection's control plane instead. An
    https connection keeps the remote mark, so the call relays; any other
    transport, or a pinned DSN, is a database this machine opens directly, so
    the mark is cleared for the call. The ContextVar token restores the
    invocation's own mark when the call ends.
    """
    if control_plane_is_remote(env):
        return remote_control_plane()
    return local_authority_exempt()


__all__ = ["connection_locality", "control_plane_is_remote", "control_plane_locality"]
