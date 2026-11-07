"""Delivery-confirmed startup-orientation state for one harness session.

Orientation is composed in one short-lived hook request and printed for the
harness to read. Between those two moments the block can still be lost: a
deny replaces the allow stdout it was merged into, and a hook the harness
kills on its own timeout never prints anything at all. The session that
misses it never gets a second startup, so recording "composed" as if it
were "delivered" turns one bad moment into a whole session with no bearings
— the shape a live Cursor session hit during a relay-turbulence window.

This module keeps the facts apart. A request *claims* the attempt before it
composes; *delivery* is confirmed only by a request that survived to return
an allow, and a request that finished without delivering *settles* its
attempt as lost. A claim another request still holds keeps sibling hooks
silent: Cursor runs parallel tool calls' postToolUse hooks at once, and
without the claim each of them re-delivered the block. A lost or abandoned
attempt lets the next context-bearing event re-deliver the block once.

Every fact is a filesystem marker, decided under one per-session file lock,
because hook events run in separate processes and resident threads. The
request-scoped handle exists only so confirming and settling callers do not
re-derive a session id they never parsed.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import sys
import time

from pathlib import Path
from typing import Optional

from filelock import FileLock, Timeout

from yoke_contracts.hook_budget import (
    HARNESS_TIMEOUT_HEADROOM_MS,
    harness_budget_ceiling_ms,
)
from yoke_contracts.hook_runner.chain_registry import (
    PRE_COMPACT_EVENT,
    SESSION_START_EVENT,
)


__all__ = [
    "claim_orientation_attempt",
    "confirm_orientation_delivery",
    "orientation_delivered",
    "reset_orientation_delivery",
    "resets_orientation",
    "settle_orientation_attempt",
]

# SessionStart sources (Claude, Codex) that start over with a fresh context
# window inside the same session.
_CONTEXT_RESET_SOURCES = frozenset({"clear", "compact"})

# No hook request outlives the shortest harness hook timeout, so a claim older
# than that belongs to a request the harness killed.
_CLAIM_STALE_SECONDS = (harness_budget_ceiling_ms() + HARNESS_TIMEOUT_HEADROOM_MS) / 1000
_LOCK_TIMEOUT_SECONDS = 2.0
_COMPOSING = "composing"
_LOST = "lost"

# Set by ``claim_orientation_attempt``; read by ``confirm_orientation_delivery``
# and ``settle_orientation_attempt`` later in the same hook request.
_composed_session: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "yoke_composed_orientation_session", default=None
)


def _marker(name: str) -> Path:
    from yoke_core.domain.project_scratch_dir import hook_marker_path

    return hook_marker_path(name)


def _attempt_marker(session_id: str) -> Path:
    return _marker(f"session-orientation-{session_id}")


def _delivered_marker(session_id: str) -> Path:
    return _marker(f"session-orientation-delivered-{session_id}")


def _lock(session_id: str) -> FileLock:
    return FileLock(
        str(_marker(f"session-orientation-{session_id}.lock")),
        timeout=_LOCK_TIMEOUT_SECONDS,
    )


def _exists(marker: Path) -> bool:
    try:
        return marker.exists()
    except OSError:
        return False


def _read_attempt(session_id: str) -> Optional[dict]:
    """The attempt record, ``{}`` for an unreadable one, ``None`` when absent."""
    marker = _attempt_marker(session_id)
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}


def _write_attempt(session_id: str, state: str) -> None:
    _attempt_marker(session_id).write_text(
        json.dumps({"state": state, "at": time.time()}) + "\n", encoding="utf-8"
    )


def _claim_is_live(attempt: dict) -> bool:
    try:
        age = time.time() - float(attempt.get("at", 0))
    except (TypeError, ValueError):
        return False
    return attempt.get("state") == _COMPOSING and age < _CLAIM_STALE_SECONDS


def orientation_delivered(session_id: str) -> bool:
    """Return whether *session_id* already received its orientation block."""
    return _exists(_delivered_marker(session_id))


def claim_orientation_attempt(session_id: str) -> Optional[bool]:
    """Claim the right to compose *session_id*'s orientation for this request.

    ``None`` means compose nothing: the block was delivered, or another
    request holds a live claim. ``False`` is a first attempt; ``True`` means
    an earlier attempt was lost, so callers say so in the block they
    re-deliver. A marker store this machine cannot write degrades toward
    orienting again: a duplicated block is recoverable, a missing one is not.
    """
    try:
        with _lock(session_id):
            if orientation_delivered(session_id):
                return None
            attempt = _read_attempt(session_id)
            if attempt and _claim_is_live(attempt):
                return None
            _write_attempt(session_id, _COMPOSING)
    except Timeout:
        return None
    except OSError:
        attempt = None
    _composed_session.set(session_id)
    return attempt is not None


def confirm_orientation_delivery(emitted_body: str) -> None:
    """Record the exact emitted context body as UTF-8 bytes and SHA-256.

    The body includes any context merged with the orientation, without its
    harness JSON envelope. It is evidence of hook emission, not agent receipt.

    Callers reach here only on an allow exit code, because a deny prints its
    block message instead of the merged allow stdout and a killed hook never
    returns. Leaving delivery unconfirmed in those cases is exactly what
    makes the next context-bearing event re-deliver the block.
    """
    session_id = _composed_session.get()
    if session_id is None:
        return
    body = emitted_body.encode("utf-8")
    marker = _delivered_marker(session_id)
    try:
        marker.write_text(
            json.dumps(
                {"byte_count": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        sys.stderr.write(
            f"WARNING: orientation_delivery_marker_unwritable: {marker}: {exc}. "
            "Restore write access to the hook-markers directory or set "
            "YOKE_SCRATCH_ROOT to a writable path; retry the context-bearing hook.\n"
        )
        return
    _composed_session.set(None)


def settle_orientation_attempt() -> None:
    """Mark this request's unconfirmed attempt lost so the next event repairs it."""
    session_id = _composed_session.get()
    if session_id is None:
        return
    _composed_session.set(None)
    try:
        with _lock(session_id):
            if not orientation_delivered(session_id):
                _write_attempt(session_id, _LOST)
    except (OSError, Timeout):
        # The claim then goes stale after the harness hook timeout instead.
        return


def resets_orientation(event_name: str, payload: dict) -> bool:
    """Whether this event empties the session's context of its orientation.

    Claude and Codex fire SessionStart with ``source`` ``clear`` or
    ``compact`` after the context restarts; Cursor reports only the coming
    compaction, on ``PreCompact``. Either way the next orientation event
    must deliver the block again.
    """
    if event_name == PRE_COMPACT_EVENT:
        return True
    return (
        event_name == SESSION_START_EVENT
        and payload.get("source") in _CONTEXT_RESET_SOURCES
    )


def reset_orientation_delivery(session_id: str) -> None:
    """A cleared context needs a fresh delivery, including retry after a lost hook."""
    for marker in (_attempt_marker(session_id), _delivered_marker(session_id)):
        try:
            marker.unlink(missing_ok=True)
        except OSError as exc:
            sys.stderr.write(
                f"WARNING: orientation_delivery_reset_failed: {marker}: {exc}. "
                "Restore write access to the hook-markers directory; until then "
                "this session will not get its orientation back after compaction.\n"
            )
