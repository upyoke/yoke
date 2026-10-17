"""Locked machine-runtime setting writes, confined to the closed catalog."""

from pathlib import Path
from typing import Any

from yoke_cli.config import machine_config_mutation as mutation
from yoke_contracts.machine_config.settings_keys import MACHINE_SETTING_KEYS


@mutation.serialized_mutation
def write_setting(
    key: str, value: Any = None, *, unset: bool = False, path: str | Path | None = None
):
    if key not in MACHINE_SETTING_KEYS:
        raise ValueError(
            f"setting_key_unknown: {key}. Recovery: yoke settings list --scope machine"
        )
    if not unset:
        value = MACHINE_SETTING_KEYS[key].validate(key, value)
        if key == "distribution":
            from yoke_cli.config.distribution import validate

            value = validate(**value)
    payload, cfg_path = mutation.load_payload(path)
    settings = payload.setdefault("settings", {})
    if not isinstance(settings, dict):
        raise ValueError(
            "setting_document_invalid: settings must be an object. Recovery: repair machine config, then retry"
        )
    if unset:
        if key not in settings:
            return
        settings.pop(key)
    else:
        settings[key] = value
    mutation.write_payload(payload, cfg_path, allow_unconfigured=True)
