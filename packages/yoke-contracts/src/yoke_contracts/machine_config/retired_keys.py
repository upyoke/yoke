"""Machine-config keys Yoke no longer reads, and what replaced them.

Launch model choice used to live in each machine's ``config.json``, so one
machine's file silently decided models for the fleet. Levels replaced it:
a launch names a level and Yoke picks among that level's options, or the
caller names an exact selection for one launch.

A file that still carries a retired key keeps loading -- refusing it would
take a working machine offline over a value nothing reads. ``yoke status``
names each one as a warning, and the next validated config write drops it.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.machine_config.schema_projects import ValidationIssue, _warn

_LEVELS_CORRECTION = (
    "launches read level options instead (`yoke universe levels get`); name "
    "--level LEVEL, or --surface/--model/--reasoning-effort for one explicit "
    "launch"
)

#: Retired key -> what replaced it.
RETIRED_MACHINE_CONFIG_KEYS: Mapping[str, str] = {
    "preferred_session_models": _LEVELS_CORRECTION,
    "preferred_session_reasoning_efforts": _LEVELS_CORRECTION,
    "session_model_routing": _LEVELS_CORRECTION,
}


def retired_key_issues(payload: Mapping[str, Any]) -> list[ValidationIssue]:
    """One warning per retired key still present in ``payload``."""
    return [
        _warn(
            "machine_config_key_retired",
            f"{key} is retired and no longer read; {correction}",
            path=key,
            hint="The next config write removes it, or delete the key by hand.",
        )
        for key, correction in RETIRED_MACHINE_CONFIG_KEYS.items()
        if key in payload
    ]


def strip_retired_keys(payload: dict[str, Any]) -> tuple[str, ...]:
    """Remove every retired key from ``payload`` and name what was removed."""
    removed = tuple(key for key in RETIRED_MACHINE_CONFIG_KEYS if key in payload)
    for key in removed:
        payload.pop(key)
    return removed


__all__ = [
    "RETIRED_MACHINE_CONFIG_KEYS",
    "retired_key_issues",
    "strip_retired_keys",
]
