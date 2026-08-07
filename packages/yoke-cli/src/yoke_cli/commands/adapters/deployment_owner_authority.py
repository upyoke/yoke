"""Owner-only connection gate for deployment-run creation surfaces.

Run rows live on the control-plane database. Creating them through the HTTPS
product plane means create dies with the plane under deploy — the same
circular exposure as GitHub status through that plane. Owner-only
local-postgres (``*-db-admin`` or ``local``) keeps create writable when the
product API process is unavailable.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.machine_config.schema import DB_ADMIN_ENV_SUFFIX


def https_product_plane_create_error(operation: str) -> Optional[str]:
    """Return an error when the active connection is the HTTPS product plane.

    ``None`` means the active connection is local-postgres (or unresolved in
    a way that should not block — let dispatch report its own failure).
    """
    try:
        from yoke_cli.transport.https import (
            TransportError,
            resolve_https_connection,
        )
    except ImportError:
        return None
    try:
        https = resolve_https_connection()
    except TransportError as exc:
        return (
            f"{operation} cannot use a broken HTTPS connection: {exc}; "
            "switch to an owner-only local-postgres env "
            f"(<plane>{DB_ADMIN_ENV_SUFFIX} or local)"
        )
    if https is None:
        return None
    env = https.env or "<env>"
    return (
        f"{operation} requires an owner-only local-postgres connection "
        f"({env}{DB_ADMIN_ENV_SUFFIX} or local), not the HTTPS product plane "
        f"{env!r}; run records must stay writable when that plane is the "
        "deploy target"
    )


__all__ = ["https_product_plane_create_error"]
