"""The queue postures a session may stamp about itself.

Shared rather than domain-owned because the CLI declares these as the
accepted values of ``--mode``: a stamp the domain would refuse is better
refused at the flag, with the vocabulary named, than relayed and bounced.
"""

from __future__ import annotations

from typing import FrozenSet


SESSION_MODE_PARKED = "parked"
SESSION_MODE_DEFAULT = "wait"
# Grounded stamps: skill ``--mode`` values, NextAction kinds, and packet
# posture. Every skill that stamps a posture on entry needs its own value
# here, or the stamp its body teaches is refused.
SESSION_MODES: FrozenSet[str] = frozenset(
    (
        SESSION_MODE_DEFAULT,
        SESSION_MODE_PARKED,
        "blitz",
        "busy",
        "charge",
        "conduct",
        "curate",
        "dash",
        "doctor",
        "escalate",
        "feed",
        "idea",
        "implement",
        "operator",
        "polish",
        "refine",
        "resume",
        "shepherd",
        "simulate",
        "steer",
        "strategize",
        "usher",
        "wrapup",
    )
)


__all__ = ["SESSION_MODES", "SESSION_MODE_DEFAULT", "SESSION_MODE_PARKED"]
