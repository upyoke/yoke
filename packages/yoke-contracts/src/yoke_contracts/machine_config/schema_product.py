"""Product-client boundary helpers for machine-config connections."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.machine_config.schema_projects import (
    _error,
)
from yoke_contracts.machine_config.schema_transport import (
    POSTGRES_TRANSPORTS,
    PRODUCT_CLIENT_TRANSPORTS,
)


def product_client_connection(
    payload: Mapping[str, Any],
    *,
    explicit_env: str | None = None,
) -> Mapping[str, Any]:
    """Return the selected connection for a product-client command."""
    from yoke_contracts.machine_config import schema as contract

    connection = contract.active_connection(payload, explicit_env=explicit_env)
    transport = str(connection.get("transport") or "").strip()
    if transport in PRODUCT_CLIENT_TRANSPORTS or transport in POSTGRES_TRANSPORTS:
        return connection
    if transport:
        issue = _error(
            "product_transport_unsupported",
            (
                f"transport {transport!r} is not supported by the product "
                "client; use an HTTPS or local-core API env."
            ),
            hint="Repair the connection with `yoke connection set`.",
        )
        hint = f" Hint: {issue.hint}" if issue.hint else ""
        raise contract.MachineConfigContractError(
            f"{issue.code}: {issue.message}{hint}"
        )
    return connection
