"""Bind the hosted release bridge to the control plane owning the run."""

from __future__ import annotations

from yoke_contracts.api_urls import validate_control_api_url
from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.schema import (
    active_connection,
    same_universe_https_env,
    TRANSPORT_HTTPS,
)
from yoke_core.domain.hosted_promotion_receipt import HOSTED_BRIDGE_WORKFLOW


def hosted_bridge_inputs(
    workflow: str, values: dict[str, str]
) -> tuple[dict[str, str], str]:
    """Seal the owner endpoint for every bridge dispatch, including retries."""
    if workflow != HOSTED_BRIDGE_WORKFLOW:
        return values, ""
    try:
        config = machine_config.load_config()
        connection = active_connection(config)
        if connection.get("transport") != TRANSPORT_HTTPS:
            sibling = same_universe_https_env(config, connection["env"])
            if not sibling:
                raise ValueError("no paired HTTPS connection")
            connection = active_connection(config, explicit_env=sibling)
        endpoint = validate_control_api_url(connection.get("api_url", ""))
    except (RuntimeError, ValueError, OSError):
        return values, (
            "release_control_endpoint_unavailable: the run's owning connection "
            "needs a credential-free HTTPS api_url. Configure it (or its paired "
            "HTTPS connection for a database-admin driver) with "
            "`yoke connection set <owning-env> --transport https --api-url HTTPS-URL`."
        )
    return {**values, "control_plane_api_url": endpoint}, ""
