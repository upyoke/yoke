"""Owner-only connection gate for deployment-run creation surfaces.

Run rows live on the control-plane database. Creating them through the HTTPS
product plane means create dies with the plane under deploy — the same
circular exposure as GitHub status through that plane. The configured
same-universe owner connection keeps create writable when the product API
process is unavailable.
"""

from __future__ import annotations

from typing import Optional


def _same_universe_admin_env(env: str) -> str:
    try:
        from yoke_cli.config import machine_config
        from yoke_contracts.machine_config.schema import (
            same_universe_db_admin_env,
        )

        return same_universe_db_admin_env(machine_config.load_config(), env)
    except Exception:
        return ""


def _repair(env: str) -> str:
    admin_env = _same_universe_admin_env(env)
    if admin_env:
        return f"switch to the configured same-universe env {admin_env!r}"
    return (
        "configure a same-universe owner-only local-postgres env; "
        "inspect configured connections with `yoke env list`"
    )


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
        env = ""
        try:
            from yoke_cli.config import machine_config

            env = machine_config.active_env()
        except Exception:
            pass
        return (
            f"{operation} cannot use a broken HTTPS connection: {exc}; "
            f"{_repair(env)}"
        )
    if https is None:
        return None
    env = https.env or "<env>"
    return (
        f"{operation} requires an owner-only local-postgres connection "
        f"and cannot use the HTTPS product plane "
        f"{env!r}; run records must stay writable when that plane is the "
        f"deploy target; {_repair(env)}"
    )


__all__ = ["https_product_plane_create_error"]
