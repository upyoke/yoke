"""Persist the installed product's distribution selection."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import machine_config_mutation as mutation
from yoke_contracts.machine_config import distribution


@mutation.serialized_mutation
def _save(*, origin: str, channel: str, path: str | Path | None = None) -> dict:
    selected = distribution.validate(origin=origin, channel=channel)
    payload, cfg_path = mutation.load_payload(path)
    settings = payload.setdefault("settings", {})
    if not isinstance(settings, dict):
        raise distribution.DistributionError(
            "distribution_settings_invalid: repair settings to an object"
        )
    settings[distribution.DISTRIBUTION_KEY] = selected
    mutation.write_payload(payload, cfg_path, allow_unconfigured=True)
    return {"path": str(cfg_path), **selected}


def save(*, origin: str, channel: str, path: str | Path | None = None) -> dict:
    """Use the existing serialized, validated machine-config writer."""
    try:
        return _save(origin=origin, channel=channel, path=path)
    except (mutation.MachineConfigWriteError, OSError) as exc:
        raise distribution.DistributionError(f"distribution_record_failed: {exc}") from exc
