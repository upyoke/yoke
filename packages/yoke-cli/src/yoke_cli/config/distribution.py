"""Persist the installed product's distribution in machine configuration."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import machine_config, machine_config_mutation as mutation
from yoke_cli.self_host import release_target

DISTRIBUTION_KEY = "distribution"
SELECT_COMMAND = "yoke config distribution set --origin URL --channel NAME"


class DistributionError(RuntimeError):
    """A distribution selection is missing, invalid, or could not be saved."""


def validate(*, origin: object, channel: object) -> dict[str, str]:
    """Require an explicit credential-free HTTP(S) origin and channel."""
    if not isinstance(origin, str) or not origin.strip():
        raise DistributionError(
            f"distribution_origin_missing: no recorded install origin; run `{SELECT_COMMAND}`"
        )
    try:
        selected = release_target.distribution_base_url(origin)
    except release_target.ReleaseTargetError as exc:
        raise DistributionError(
            f"distribution_origin_invalid: repair the origin with `{SELECT_COMMAND}`"
        ) from exc
    try:
        if not isinstance(channel, str):
            raise release_target.ReleaseTargetError("channel is missing")
        release_target.release_channel(channel)
    except release_target.ReleaseTargetError as exc:
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


@mutation.serialized_mutation
def _save(*, origin: str, channel: str, path: str | Path | None = None) -> dict:
    selected = validate(origin=origin, channel=channel)
    payload, cfg_path = mutation.load_payload(path)
    settings = payload.setdefault("settings", {})
    if not isinstance(settings, dict):
        raise DistributionError(
            "distribution_settings_invalid: repair settings to an object"
        )
    settings[DISTRIBUTION_KEY] = selected
    mutation.write_payload(payload, cfg_path, allow_unconfigured=True)
    return {"path": str(cfg_path), **selected}


def save(*, origin: str, channel: str, path: str | Path | None = None) -> dict:
    """Use the existing serialized, validated machine-config writer."""
    try:
        return _save(origin=origin, channel=channel, path=path)
    except (mutation.MachineConfigWriteError, OSError) as exc:
        raise DistributionError(f"distribution_record_failed: {exc}") from exc
