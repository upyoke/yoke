"""Read and validate the installed product's distribution selection."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from yoke_contracts.machine_config import reader as machine_config
from yoke_contracts import distribution_target
from yoke_contracts.api_urls import (
    DISTRIBUTION_PROD_URL,
    DISTRIBUTION_STAGE_URL,
    HOSTED_PROD_API_URL,
    HOSTED_STAGE_API_URL,
)

DISTRIBUTION_KEY = "distribution"
SELECT_COMMAND = "yoke settings set distribution '<JSON with origin and channel>'"


class DistributionError(RuntimeError):
    """A distribution selection is missing, invalid, or could not be saved."""


def validate(*, origin: object, channel: object) -> dict[str, str]:
    """Require an explicit credential-free HTTP(S) origin and channel."""
    if not isinstance(origin, str) or not origin.strip():
        raise DistributionError(
            f"distribution_origin_missing: no recorded install origin; run `{SELECT_COMMAND}`"
        )
    try:
        selected = distribution_target.distribution_base_url(origin)
    except distribution_target.ReleaseTargetError as exc:
        raise DistributionError(
            f"distribution_origin_invalid: repair the origin with `{SELECT_COMMAND}`"
        ) from exc
    try:
        if not isinstance(channel, str):
            raise distribution_target.ReleaseTargetError("channel is missing")
        distribution_target.release_channel(channel)
    except distribution_target.ReleaseTargetError as exc:
        raise DistributionError(
            "distribution_channel_invalid: select a published channel "
            f"with `{SELECT_COMMAND}`"
        ) from exc
    return {"origin": selected, "channel": channel}


def recorded(*, path: str | Path | None = None) -> dict[str, str]:
    """Read the install record without inferring an upstream distribution."""
    try:
        payload = machine_config.load_config(path)
    except (machine_config.MachineConfigError, OSError) as exc:
        raise DistributionError(f"distribution_config_unreadable: {exc}") from exc
    settings = payload.get("settings")
    value = settings.get(DISTRIBUTION_KEY) if isinstance(settings, dict) else None
    value = value if isinstance(value, dict) else {}
    return validate(origin=value.get("origin"), channel=value.get("channel"))


def origin_for_connection(
    connection: Mapping[str, Any], *, path: str | Path | None = None
) -> str:
    """Pick the distribution that publishes the control plane a connection names.

    Hosted production and stage each publish from their own origin; any other
    connection uses the install's recorded origin.
    """
    hostname = urlsplit(str(connection.get("api_url") or "")).hostname
    if hostname == urlsplit(HOSTED_PROD_API_URL).hostname:
        return DISTRIBUTION_PROD_URL
    if hostname == urlsplit(HOSTED_STAGE_API_URL).hostname:
        return DISTRIBUTION_STAGE_URL
    return recorded(path=path)["origin"]
