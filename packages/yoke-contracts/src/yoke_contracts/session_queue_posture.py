"""The queue postures a session may stamp about itself.

Shared rather than domain-owned because the CLI declares these as the
accepted values of ``--mode``: a stamp the domain would refuse is better
refused at the flag, with the vocabulary named, than relayed and bounced.
"""

from __future__ import annotations

from typing import FrozenSet
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
        "operator",
        "resume",
    )
)


__all__ = ["SESSION_MODES", "SESSION_MODE_DEFAULT", "SESSION_MODE_PARKED"]
