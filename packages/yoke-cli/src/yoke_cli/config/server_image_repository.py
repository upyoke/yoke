"""Select and persist the self-host image repository in machine settings."""

from pathlib import Path
import re

from yoke_cli.config import machine_config, machine_config_mutation as mutation
from yoke_contracts.server_image import PUBLISHED_SERVER_IMAGE_REPOSITORY

SETTING_KEY = "server_image_repository"
_REPOSITORY = re.compile(
    r"[a-z0-9][a-z0-9.-]*(?::[0-9]+)?(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+"
)


def validate(value: str) -> str:
    """Require a repository without credentials, a tag, or a digest."""
    if not isinstance(value, str) or not _REPOSITORY.fullmatch(value):
        raise ValueError(
            "server_image_repository_invalid: enter a lowercase registry/repository "
            "without a scheme, credentials, tag, or digest; repair "
            f"settings.{SETTING_KEY} in machine config or choose Image repository in onboarding"
        )
    return value


def configured(*, path: str | Path | None = None) -> str:
    """Use the published repository only when no override is configured."""
    try:
        settings = machine_config.load_config(path).get("settings", {})
    except (machine_config.MachineConfigError, OSError) as exc:
        raise ValueError(
            f"server_image_config_unreadable: repair machine config, then retry: {exc}"
        ) from exc
    if not isinstance(settings, dict):
        raise ValueError(
            "server_image_settings_invalid: repair machine settings to an object"
        )
    return validate(settings.get(SETTING_KEY, PUBLISHED_SERVER_IMAGE_REPOSITORY))


@mutation.serialized_mutation
def save(value: str, *, path: str | Path | None = None) -> None:
    """Reuse the serialized, validated machine-config writer."""
    selected = validate(value)
    payload, cfg_path = mutation.load_payload(path)
    settings = payload.setdefault("settings", {})
    if not isinstance(settings, dict):
        raise ValueError(
            "server_image_settings_invalid: repair machine settings to an object"
        )
    settings[SETTING_KEY] = selected
    mutation.write_payload(payload, cfg_path, allow_unconfigured=True)
