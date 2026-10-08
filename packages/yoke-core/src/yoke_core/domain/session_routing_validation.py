"""The write boundary for a project's ``session-routing`` settings.

The document carries one key: ``levels``, the project's override of the
universe execution levels (see :mod:`yoke_contracts.levels`). Every
capability writer passes through this module, so ``set``, ``merge``, and a
create all refuse the same documents with the same named reasons.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.levels import LEVELS_KEY, LevelsError, parse_levels
from yoke_contracts.session_level import (
    renamed_routing_keys,
    retired_lane_setting_keys,
    retired_level_routing_keys,
    retired_process_offer_keys,
)
from yoke_core.domain import json_helper

_OVERRIDE_RECIPE = (
    "Write the project's override as "
    "`yoke projects capability-settings set --project P --cap-type "
    "session-routing --settings-json '{\"levels\": [...]}'`, or remove the "
    "capability so the project reads the universe levels "
    "(`yoke universe levels get`)."
)


class SessionRoutingSettingsError(ValueError):
    """Raised when a ``session-routing`` document cannot be stored as written."""

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


def _refuse_retired(settings: Mapping[str, Any]) -> None:
    retired_process = retired_process_offer_keys(settings)
    if retired_process:
        raise SessionRoutingSettingsError(
            "process_offer_policy_retired: remove these settings keys. "
            "Steering assigns process work explicitly. " + _OVERRIDE_RECIPE,
            field=", ".join(retired_process),
        )
    retired_lane = retired_lane_setting_keys(settings)
    if retired_lane:
        raise SessionRoutingSettingsError(
            "lane_action_allowlists_retired: remove these settings keys. "
            + _OVERRIDE_RECIPE,
            field=", ".join(retired_lane),
        )
    renamed = sorted(renamed_routing_keys(settings))
    retired_level = sorted(retired_level_routing_keys(settings))
    if renamed or retired_level:
        raise SessionRoutingSettingsError(
            "level_routing_keys_retired: levels are ordered lists of launchable "
            "options, and a session's level is the one whose option matches "
            "its harness, model, and effort; declared metadata, selector "
            "rules, and harness defaults no longer exist. " + _OVERRIDE_RECIPE,
            field=", ".join(renamed + retired_level),
        )


def validate_session_routing_settings(settings: Mapping[str, Any]) -> None:
    """Refuse a ``session-routing`` document that cannot be labeled or launched on."""
    if not isinstance(settings, Mapping):
        raise SessionRoutingSettingsError(
            f"settings must be a JSON object; got {type(settings).__name__}.",
            field="settings",
        )
    _refuse_retired(settings)
    unknown = sorted(key for key in settings if key != LEVELS_KEY)
    if unknown:
        raise SessionRoutingSettingsError(
            f"session_routing_key_unknown: the document holds only "
            f"{LEVELS_KEY!r}. " + _OVERRIDE_RECIPE,
            field=", ".join(unknown),
        )
    if LEVELS_KEY not in settings:
        raise SessionRoutingSettingsError(
            "session_routing_levels_missing: an override must carry its levels. "
            + _OVERRIDE_RECIPE,
            field=LEVELS_KEY,
        )
    try:
        parse_levels(settings[LEVELS_KEY])
    except LevelsError as exc:
        raise SessionRoutingSettingsError(
            f"{exc.code}: {exc.detail}", field=exc.field
        ) from exc


def validate_json_string(raw_json: str) -> str:
    """Validate a ``session-routing`` document and return it canonicalized."""
    payload = json_helper.loads_text(raw_json)
    if not isinstance(payload, dict):
        raise SessionRoutingSettingsError(
            "settings must be a JSON object.", field="settings"
        )
    validate_session_routing_settings(payload)
    return json_helper.dumps_compact(payload)


__all__ = [
    "SessionRoutingSettingsError",
    "validate_json_string",
    "validate_session_routing_settings",
]
