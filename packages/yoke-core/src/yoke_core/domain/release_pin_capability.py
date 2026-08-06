"""Typed routing contract for project-owned release-pin recording."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_contracts.release_pin import (
    DESIRED_PIN_PATH_KEY,
    ENVIRONMENT_BY_TARGET_KEY,
    PROBE_URL_PATH_KEY,
    RELEASE_PIN_CAPABILITY,
    SERVED_PIN_RESPONSE_PATH_KEY,
)
from yoke_core.domain import json_helper
from yoke_core.domain.settings_cas import apply_key_path_assignments


CAPABILITY_TYPE = RELEASE_PIN_CAPABILITY


@dataclass(frozen=True)
class ReleasePinRoute:
    """The exact environment row and scalar path one target may mutate."""

    environment_id: str
    desired_pin_path: str


def validate_settings(settings: Mapping[str, Any]) -> None:
    """Validate the generic capability document.

    Returns ``None`` because validation covers every configured target rather
    than selecting one.  ``route_for_target`` performs selection after this
    common validation.
    """
    mapping = settings.get(ENVIRONMENT_BY_TARGET_KEY)
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError(
            f"{CAPABILITY_TYPE}.{ENVIRONMENT_BY_TARGET_KEY} must be a non-empty object"
        )
    for target, environment_id in mapping.items():
        if not isinstance(target, str) or not target.strip():
            raise ValueError(
                f"{CAPABILITY_TYPE}.{ENVIRONMENT_BY_TARGET_KEY} target names "
                "must be non-empty strings"
            )
        if not isinstance(environment_id, str) or not environment_id.strip():
            raise ValueError(
                f"{CAPABILITY_TYPE}.{ENVIRONMENT_BY_TARGET_KEY}[{target!r}] "
                "must be a non-empty environment id"
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


def route_for_target(settings: Mapping[str, Any], target: str) -> ReleasePinRoute:
    """Resolve one deploy target without accepting caller-supplied DB paths."""
    validate_settings(settings)
    normalized_target = str(target or "").strip()
    mapping = settings[ENVIRONMENT_BY_TARGET_KEY]
    assert isinstance(mapping, dict)
    environment_id = mapping.get(normalized_target)
    if not environment_id:
        raise LookupError(
            f"{CAPABILITY_TYPE}.{ENVIRONMENT_BY_TARGET_KEY} has no entry for "
            f"{normalized_target!r}"
        )
    return ReleasePinRoute(
        environment_id=str(environment_id).strip(),
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
    "ENVIRONMENT_BY_TARGET_KEY",
    "PROBE_URL_PATH_KEY",
    "ReleasePinRoute",
    "SERVED_PIN_RESPONSE_PATH_KEY",
    "route_for_target",
    "validate_json_string",
    "validate_settings",
]
