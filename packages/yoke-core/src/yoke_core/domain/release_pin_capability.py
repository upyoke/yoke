"""Typed routing contract for project-owned release-pin recording."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_contracts.release_pin import (
    DESIRED_PIN_PATH_KEY,
    PROBE_URL_PATH_KEY,
    RELEASE_PIN_CAPABILITY,
    SERVED_PIN_RESPONSE_PATH_KEY,
)
from yoke_core.domain import json_helper
from yoke_core.domain.settings_cas import apply_key_path_assignments


CAPABILITY_TYPE = RELEASE_PIN_CAPABILITY
_ALLOWED_SETTING_KEYS = frozenset(
    {
        DESIRED_PIN_PATH_KEY,
        PROBE_URL_PATH_KEY,
        SERVED_PIN_RESPONSE_PATH_KEY,
    }
)


@dataclass(frozen=True)
class ReleasePinRoute:
    """The registered environment name and scalar path one target may mutate."""

    environment: str
    desired_pin_path: str


def validate_settings(settings: Mapping[str, Any]) -> None:
    """Validate the generic capability document.

    Environment authority comes from the project registry. The capability
    owns only the settings and probe paths used for every registered
    environment.
    """
    unknown_keys = sorted(set(settings) - _ALLOWED_SETTING_KEYS)
    if unknown_keys:
        raise ValueError(
            f"{CAPABILITY_TYPE} has unknown setting(s): "
            f"{', '.join(unknown_keys)}"
        )
    _validate_path(
        settings,
        DESIRED_PIN_PATH_KEY,
        purpose="one scalar environment-settings path",
    )
    verification_keys = (PROBE_URL_PATH_KEY, SERVED_PIN_RESPONSE_PATH_KEY)
    configured_verification_keys = [key for key in verification_keys if key in settings]
    if configured_verification_keys and len(configured_verification_keys) != len(
        verification_keys
    ):
        missing = next(key for key in verification_keys if key not in settings)
        raise ValueError(
            f"{CAPABILITY_TYPE}.{missing} is required when release-pin "
            "verification is configured"
        )
    for key, purpose in (
        (PROBE_URL_PATH_KEY, "the probe URL environment-settings path"),
        (SERVED_PIN_RESPONSE_PATH_KEY, "the served-pin response path"),
    ):
        if key in settings:
            _validate_path(settings, key, purpose=purpose)
    return None


def _validate_path(settings: Mapping[str, Any], key: str, *, purpose: str) -> None:
    raw_path = settings.get(key)
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"{CAPABILITY_TYPE}.{key} must explicitly name {purpose}")
    normalized_path = raw_path.strip()
    try:
        apply_key_path_assignments({}, {normalized_path: "validation"})
    except ValueError as exc:
        raise ValueError(f"{CAPABILITY_TYPE}.{key} is invalid: {exc}") from exc


def route_for_environment(
    settings: Mapping[str, Any], environment: str,
) -> ReleasePinRoute:
    """Select one registered-name route without accepting aliases or row keys."""
    validate_settings(settings)
    from yoke_core.domain.environment_reference import validate_name

    normalized_environment = validate_name(environment)
    return ReleasePinRoute(
        environment=normalized_environment,
        desired_pin_path=str(settings[DESIRED_PIN_PATH_KEY]).strip(),
    )


def validate_json_string(raw_json: str) -> str:
    """Validate and canonicalize one stored release-pin capability document."""
    payload = json_helper.loads_text(raw_json)
    if not isinstance(payload, dict):
        raise ValueError(f"{CAPABILITY_TYPE} settings must be a JSON object")
    validate_settings(payload)
    return json_helper.dumps_compact(payload)


__all__ = [
    "CAPABILITY_TYPE",
    "DESIRED_PIN_PATH_KEY",
    "PROBE_URL_PATH_KEY",
    "ReleasePinRoute",
    "SERVED_PIN_RESPONSE_PATH_KEY",
    "route_for_environment",
    "validate_json_string",
    "validate_settings",
]
