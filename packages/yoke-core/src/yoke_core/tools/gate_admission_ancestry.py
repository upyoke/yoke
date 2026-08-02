"""The admission state a gate publishes to the processes it spawns.

Queueing is only ever correct between peers. A descendant that waits on a
slot its own ancestor is blocking on is not queued, it is deadlocked — the
ancestor cannot finish until the descendant does. Telling those apart needs
more than "an ancestor exists", so a gate publishes *what it holds* through
the environment and its descendants read that back here.

Three situations, and the arbitration loop in
:mod:`yoke_core.tools.gate_admission` behaves differently on each: ride the
ancestor's slot, proceed immediately because the ancestor holds nothing, or
arbitrate for a slot of one's own.
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterator, Optional


#: Set for the duration of any gate that has resolved its own admission,
#: and inherited by every process it spawns.
ADMITTED_ENV = "YOKE_TEST_GATE_SLOT_HELD"

#: The ancestor holds a real slot; descendants ride it.
MARKER_SLOT_HELD = "slot"

#: The ancestor resolved admission without holding a slot — it was
#: file-scoped, the cap was disabled, or no cluster was reachable.
MARKER_NO_SLOT = "bypass"


def admitted_environment(env: dict) -> dict:
    """Return *env* with the current admission marker mirrored in.

    Wrappers snapshot their child environment before entering the
    admission context, so the marker set on ``os.environ`` must be
    re-mirrored into that snapshot at spawn time — otherwise descendants
    never see it and arbitrate their own slots, deadlocking behind their
    ancestor.
    """
    marker = os.environ.get(ADMITTED_ENV)
    if marker:
        return {**env, ADMITTED_ENV: marker}
    return env


def ancestor_admission_state() -> Optional[str]:
    """Return what an admitted ancestor holds, or None when there is none.

    Any marker value other than :data:`MARKER_NO_SLOT` reads as a held slot,
    so a process spawned by an older build that wrote a bare truthy marker
    still rides its ancestor rather than arbitrating a second time.
    """
    marker = os.environ.get(ADMITTED_ENV)
    if not marker:
        return None
    return MARKER_NO_SLOT if marker == MARKER_NO_SLOT else MARKER_SLOT_HELD


@contextlib.contextmanager
def published_state(state: str) -> Iterator[None]:
    """Publish *state* to descendants for the duration of the block."""
    prior = os.environ.get(ADMITTED_ENV)
    os.environ[ADMITTED_ENV] = state
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(ADMITTED_ENV, None)
        else:
            os.environ[ADMITTED_ENV] = prior


__all__ = [
    "ADMITTED_ENV",
    "MARKER_NO_SLOT",
    "MARKER_SLOT_HELD",
    "admitted_environment",
    "ancestor_admission_state",
    "published_state",
]
