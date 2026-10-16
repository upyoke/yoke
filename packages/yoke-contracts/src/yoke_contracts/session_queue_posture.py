"""The queue postures a session may stamp about itself.

Shared rather than domain-owned because the CLI declares these as the
accepted values of ``--mode``: a stamp the domain would refuse is better
refused at the flag, with the vocabulary named, than relayed and bounced.
"""

from __future__ import annotations

from typing import Any, FrozenSet, Mapping
from yoke_contracts.skill_registry import SKILL_SESSION_MODES


SESSION_MODE_PARKED = "parked"
SESSION_MODE_DEFAULT = "wait"
# Non-skill postures describe scheduling and recovery.
SESSION_MODES: FrozenSet[str] = SKILL_SESSION_MODES | frozenset(
    (
        SESSION_MODE_DEFAULT,
        SESSION_MODE_PARKED,
        "busy",
        "escalate",
        "resume",
    )
)


__all__ = ["SESSION_MODES", "SESSION_MODE_DEFAULT", "SESSION_MODE_PARKED"]


def session_pause_declared(row: Mapping[str, Any]) -> bool:
    """An explicit pause; activity age never supplies this fact."""
    return bool(
        row.get("mode") == SESSION_MODE_PARKED
        or row.get("turn_posture") == "waiting"
        or row.get("declared_wait")
    )


def session_pause_mode_sql(alias: str) -> str:
    """Project persisted pause declarations into a board's existing mode cell."""
    return (
        f"CASE WHEN {alias}.mode='parked' OR to_jsonb({alias})->>'turn_posture'='waiting' "
        f"THEN 'parked' ELSE {alias}.mode END"
    )
