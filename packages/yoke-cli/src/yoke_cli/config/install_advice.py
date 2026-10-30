"""Install advice follows the connected service or recorded distribution."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from yoke_cli.config import distribution, machine_config
from yoke_contracts.api_urls import DISTRIBUTION_BASE_URL_ENV


def install_command(*, path: str | Path | None = None) -> str:
    """Compose advice without silently choosing a production origin.

    Serving processes may declare their artifact origin through the same
    environment setting as the installer. Machines prefer their connected
    hosted environment and otherwise use the installer record.
    """
    try:
        origin = os.environ.get(DISTRIBUTION_BASE_URL_ENV)
        if origin:
            from yoke_cli.self_host.release_target import distribution_base_url

            origin = distribution_base_url(origin)
        else:
            config = machine_config.load_config(path)
            connection = (
                machine_config.active_connection(path)
                if config.get("connections")
                else {}
            )
            origin = distribution.origin_for_connection(connection, path=path)
        return f"curl -fsSL {shlex.quote(origin + '/install')} | sh"
    except (OSError, RuntimeError, ValueError):
        return (
            "install_origin_unavailable: restore settings.distribution.origin "
            f"and channel with {distribution.SELECT_COMMAND}, then retry"
        )


def hosted_connect_url(api_url: object = None, env_name: object = None) -> str:
    """Fresh onboarding follows the requested hosted authority."""
    from yoke_cli.config.onboard_wizard_flow_hosted_machine import (
        platform_url_for_connection,
    )

    return platform_url_for_connection(api_url, env_name)
