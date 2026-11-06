"""The queue postures a session may stamp about itself.

A session is parked or not parked. Shared rather than domain-owned because
the CLI declares these as the accepted values of ``--mode``: a stamp the
domain would refuse is better refused at the flag, with the vocabulary
named, than relayed and bounced.
"""

from __future__ import annotations

from typing import Any, FrozenSet, Mapping


SESSION_MODE_PARKED = "parked"
SESSION_MODE_DEFAULT = "wait"
SESSION_MODES: FrozenSet[str] = frozenset((SESSION_MODE_DEFAULT, SESSION_MODE_PARKED))


__all__ = ["SESSION_MODES", "SESSION_MODE_DEFAULT", "SESSION_MODE_PARKED"]


def session_declared_wait(row: Mapping[str, Any]) -> Any:
    """Read deliberate waits; a derived between-turns marker is activity."""
    declared = row.get("declared_wait")
    if isinstance(declared, Mapping) and declared.get("kind") == "turn_posture":
        return None
    return declared


def session_pause_declared(row: Mapping[str, Any]) -> bool:
    """An explicit pause; turn posture and activity age never supply it."""
    return bool(row.get("mode") == SESSION_MODE_PARKED or session_declared_wait(row))


def session_pause_mode_sql(alias: str) -> str:
    """Project persisted pause declarations into a board's existing mode cell."""
    return f"CASE WHEN {alias}.mode='parked' THEN 'parked' ELSE {alias}.mode END"
