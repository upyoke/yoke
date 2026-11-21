"""Install advice follows the connected service or recorded distribution."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from yoke_contracts.machine_config import distribution, reader as machine_config
from yoke_contracts.api_urls import DISTRIBUTION_BASE_URL_ENV
from yoke_contracts.distribution_target import distribution_base_url


class InstallOriginUnavailable(RuntimeError):
    """The machine has no usable distribution origin for install advice."""


def install_command(*, path: str | Path | None = None) -> str:
    """Compose advice without silently choosing a production origin.

    Serving processes may declare their artifact origin through the same
    environment setting as the installer. Machines prefer their connected
    hosted environment and otherwise use the installer record.
    """
    try:
        origin = os.environ.get(DISTRIBUTION_BASE_URL_ENV)
        if origin:
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
    except (OSError, RuntimeError, ValueError) as exc:
        raise InstallOriginUnavailable(
            "install_origin_unavailable: restore settings.distribution.origin "
            f"and channel with {distribution.SELECT_COMMAND}, then retry"
        ) from exc
