"""Delivery-confirmed startup-orientation state for one harness session.

Orientation is composed in one short-lived hook process and printed for the
harness to read. Between those two moments the block can still be lost: a
deny replaces the allow stdout it was merged into, and a hook the harness
kills on its own timeout never prints anything at all. The session that
misses it never gets a second startup, so recording "composed" as if it
were "delivered" turns one bad moment into a whole session with no bearings
— the shape a live Cursor session hit during a relay-turbulence window.

This module keeps the two facts apart. An *attempt* is recorded when
orientation is composed; *delivery* is confirmed only by a composing process
that survived to return an allow. An attempt with no delivery means the
session is still un-oriented, which is what lets the next context-bearing
hook event re-deliver the block exactly once.

Both facts are filesystem markers because every hook event runs in a fresh
process. The in-process handle exists only so the confirming caller does not
have to re-derive a session id it never parsed; a process that dies before
confirming simply leaves the session un-delivered, which is the outcome the
repair path is built to notice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


__all__ = [
    "confirm_orientation_delivery",
    "orientation_delivered",
    "record_orientation_attempt",
]


# Set by ``record_orientation_attempt`` and read by
# ``confirm_orientation_delivery`` later in the same hook process.
_composed_session: Optional[str] = None


def _attempt_marker(session_id: str) -> Path:
    from yoke_core.domain.project_scratch_dir import hook_marker_path

    return hook_marker_path(f"session-orientation-{session_id}")


def _delivered_marker(session_id: str) -> Path:
    from yoke_core.domain.project_scratch_dir import hook_marker_path

    return hook_marker_path(f"session-orientation-delivered-{session_id}")


def _touch(marker: Path) -> None:
    """Arm *marker*, tolerating a scratch root this machine cannot write.

    An unwritable marker degrades toward orienting again rather than never:
    a duplicated orientation block is recoverable, a session that never gets
    one is not.
    """
    try:
        marker.touch()
    except OSError:
        pass


def _exists(marker: Path) -> bool:
    try:
        return marker.exists()
    except OSError:
        return False


def orientation_delivered(session_id: str) -> bool:
    """Return whether *session_id* already received its orientation block."""
    return _exists(_delivered_marker(session_id))


def record_orientation_attempt(session_id: str) -> bool:
    """Arm the attempt marker for *session_id*; report a prior attempt.

    ``True`` means orientation was already composed for this session once
    and never confirmed — the composing process lost it. Callers use that to
    say so in the block they are about to re-deliver.
    """
    marker = _attempt_marker(session_id)
    attempted_before = _exists(marker)
    _touch(marker)
    global _composed_session
    _composed_session = session_id
    return attempted_before


def confirm_orientation_delivery() -> None:
    """Record that this process printed the orientation it composed.

    Callers reach here only on an allow exit code, because a deny prints its
    block message instead of the merged allow stdout and a killed hook never
    returns. Leaving delivery unconfirmed in those cases is exactly what
    makes the next context-bearing event re-deliver the block.
    """
    if _composed_session is None:
        return
    _touch(_delivered_marker(_composed_session))
