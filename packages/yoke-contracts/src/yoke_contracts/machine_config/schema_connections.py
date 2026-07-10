"""Connection-level helpers for the machine-config contract."""

from __future__ import annotations

import os
from typing import Any, Mapping

from yoke_contracts.machine_config.schema_transport import POSTGRES_TRANSPORTS

ENV_OVERRIDE = "YOKE_ENV"
PROD_FLAG_KEY = "prod"


class MachineConfigContractError(RuntimeError):
    """Raised when the selected machine config cannot be used."""


def selected_env(payload: Mapping[str, Any], explicit_env: str | None = None) -> str:
    """Resolve env precedence: explicit, ``YOKE_ENV``, then ``active_env``."""
    requested = (
        (explicit_env or "").strip()
        or os.environ.get(ENV_OVERRIDE, "").strip()
    )
    configured = str(payload.get("active_env") or "").strip()
    selected = requested or configured
    if not selected:
        raise MachineConfigContractError(
            "active env is not configured; run `yoke env use <env>` or pass --env"
        )
    return selected


def connection_is_prod(connection: Mapping[str, Any]) -> bool:
    """Return the explicit prod marker without inferring from names or DSNs."""
    return connection.get(PROD_FLAG_KEY) is True


def local_postgres_envs(
    payload: Mapping[str, Any] | None,
    *,
    include_prod: bool = False,
) -> list[str]:
    """Env labels whose connection declares local-postgres.

    Retry teaching defaults to non-prod local Postgres entries only. Callers
    that need full inventory must pass ``include_prod=True`` explicitly.
    """
    if not isinstance(payload, Mapping):
        return []
    connections = payload.get("connections")
    if not isinstance(connections, Mapping):
        return []
    return sorted(
        str(env) for env, entry in connections.items()
        if isinstance(entry, Mapping)
        and str(entry.get("transport") or "").strip() in POSTGRES_TRANSPORTS
        and (include_prod or not connection_is_prod(entry))
    )


__all__ = [
    "ENV_OVERRIDE",
    "MachineConfigContractError",
    "PROD_FLAG_KEY",
    "connection_is_prod",
    "local_postgres_envs",
    "selected_env",
]
