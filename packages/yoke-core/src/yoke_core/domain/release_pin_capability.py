"""Typed routing contract for project-owned release-pin recording."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_contracts.release_pin import (
    DESIRED_PIN_PATH_KEY,
    ENVIRONMENT_BY_TARGET_KEY,
    RELEASE_PIN_CAPABILITY,
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
            f"{CAPABILITY_TYPE}.{ENVIRONMENT_BY_TARGET_KEY} must be a "
            "non-empty object"
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
    desired_pin_path = settings.get(DESIRED_PIN_PATH_KEY)
    if not isinstance(desired_pin_path, str) or not desired_pin_path.strip():
        raise ValueError(
            f"{CAPABILITY_TYPE}.{DESIRED_PIN_PATH_KEY} must explicitly name "
            "one scalar environment-settings path"
        )
    normalized_path = desired_pin_path.strip()
    try:
        apply_key_path_assignments({}, {normalized_path: "validation"})
    except ValueError as exc:
        raise ValueError(
            f"{CAPABILITY_TYPE}.{DESIRED_PIN_PATH_KEY} is invalid: {exc}"
        ) from exc
    return None


def route_for_target(
    settings: Mapping[str, Any], target: str
) -> ReleasePinRoute:
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
    "ReleasePinRoute",
    "route_for_target",
    "validate_json_string",
    "validate_settings",
]
