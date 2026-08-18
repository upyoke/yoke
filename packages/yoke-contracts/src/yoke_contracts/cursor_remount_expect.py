"""Short-lived receipt that a Cursor remount may alias onto a holder session.

Cursor remounts mint a new conversation id and do not send a parent id.
While the holder is still on the main checkout, each client hook refreshes
a receipt under ``{map_dir}/remount-expect/``. The first hook in the linked
worktree records the holder conversation's activity sequence; a later hook
aliases only when that sequence stayed unchanged. Folder occupancy alone is
not enough, and two conversations emitting hooks never share one session.

Never raises — hook bookkeeping must not break a hook. Replay writes
nothing and consumes nothing.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
import fcntl
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional, Union

from yoke_contracts.payload_session_fold import is_hook_replay


REMOUNT_EXPECT_DIR_NAME = "remount-expect"
REMOUNT_EXPECT_TTL_S = 300
REMOUNT_ABSENT = "absent"
REMOUNT_OBSERVING = "observing"
REMOUNT_CONTINUITY = "continuity"
REMOUNT_REFUSED = "refused"
REMOUNT_REFUSAL_PAYLOAD_FIELD = "cursor_fold_refusal"
_REMOUNT_OBSERVATION_EVENTS = frozenset(
    {"beforesubmitprompt", "sessionstart", "userpromptsubmit"}
)

# Same shape as the conversation-map filename guard: refuse rather than
# sanitize, so a reader never looks up a rewritten key.
_SAFE_ID = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")

_MapDir = Union[str, "os.PathLike[str]"]


@dataclass(frozen=True)
class RemountDecision:
    """One holder-conversation liveness decision for a remount candidate."""

    outcome: str
    holder_session_id: str
    holder_conversation_id: str
    arriving_conversation_id: str


def is_remount_observation_event(event_name: str) -> bool:
    """Whether this lifecycle hook can safely establish liveness observation."""
    return event_name.strip().casefold() in _REMOUNT_OBSERVATION_EVENTS


def _expect_path(map_dir: _MapDir, holder_session_id: str) -> Optional[Path]:
    if not holder_session_id or not _SAFE_ID.match(holder_session_id):
        return None
    return Path(map_dir) / REMOUNT_EXPECT_DIR_NAME / f"{holder_session_id}.json"


@contextmanager
def _exclusive_receipt(path: Path) -> Iterator[bool]:
    """Serialize one receipt mutation; yield False when locking is unavailable."""
    descriptor = -1
    locked = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(f".{path.name}.lock")
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = True
    except OSError:
        pass
    try:
        yield locked
    finally:
        if descriptor >= 0:
            try:
                if locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _read_live(path: Path) -> Optional[dict]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    expires_at = record.get("expires_at")
    if not isinstance(expires_at, str) or not expires_at:
        return None
    try:
        expires = datetime.fromisoformat(expires_at)
    except ValueError:
        return None
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires.timestamp() < time.time():
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return record


def _write_record(path: Path, record: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record, sort_keys=True)
        tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
        tmp.write_text(payload + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        return False
    return True


def write_remount_expect(
    map_dir: _MapDir,
    holder_session_id: str,
    holder_conversation_id: str = "",
) -> bool:
    """Refresh pairing evidence and the holder conversation's hook sequence.

    A pending candidate keeps the sequence it first observed. Any later hook
    from the holder conversation advances the live sequence without erasing
    that baseline, which lets the arriving conversation distinguish a quiet
    remount from a second window sharing an active holder.
    """
    if is_hook_replay():
        return False
    path = _expect_path(map_dir, holder_session_id)
    if path is None:
        return False
    conversation_id = holder_conversation_id or holder_session_id
    if not _SAFE_ID.match(conversation_id):
        return False
    with _exclusive_receipt(path) as locked:
        if not locked:
            return False
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=REMOUNT_EXPECT_TTL_S)
        existing = _read_live(path) or {}
        same_conversation = existing.get("holder_conversation_id") == conversation_id
        prior_sequence = existing.get("holder_hook_sequence", 0)
        if not isinstance(prior_sequence, int) or not same_conversation:
            prior_sequence = 0
        record = {
            "expires_at": expires.isoformat(),
            "holder_activity_at": now.isoformat(),
            "holder_conversation_id": conversation_id,
            "holder_hook_sequence": prior_sequence + 1,
            "holder_session_id": holder_session_id,
            "written_at": now.isoformat(),
        }
        if same_conversation:
            for key in (
                "candidate_conversation_id",
                "candidate_observed_sequence",
                "candidate_seen_at",
            ):
                if key in existing:
                    record[key] = existing[key]
        return _write_record(path, record)


def observe_remount_candidate(
    map_dir: _MapDir,
    holder_session_id: str,
    arriving_conversation_id: str,
) -> RemountDecision:
    """Observe once, then allow only if the holder conversation stayed quiet.

    The first hook from a new worktree conversation records the holder's hook
    sequence without granting a durable alias. A later hook from the same
    conversation proves continuity only when that sequence is unchanged. If
    the holder emitted another hook in between, or another candidate raced
    for the same receipt, the fold is refused. A successful decision consumes
    the single-use remount receipt.
    """
    path = _expect_path(map_dir, holder_session_id)
    if (
        is_hook_replay()
        or path is None
        or not arriving_conversation_id
        or not _SAFE_ID.match(arriving_conversation_id)
    ):
        return RemountDecision(
            REMOUNT_ABSENT,
            holder_session_id,
            "",
            arriving_conversation_id,
        )
    with _exclusive_receipt(path) as locked:
        if not locked:
            return RemountDecision(
                REMOUNT_REFUSED,
                holder_session_id,
                "",
                arriving_conversation_id,
            )
        return _observe_locked(
            path,
            holder_session_id,
            arriving_conversation_id,
        )


def _observe_locked(
    path: Path,
    holder_session_id: str,
    arriving_conversation_id: str,
) -> RemountDecision:
    record = _read_live(path)
    if record is None:
        return RemountDecision(
            REMOUNT_ABSENT,
            holder_session_id,
            "",
            arriving_conversation_id,
        )
    holder_conversation_id = record.get("holder_conversation_id")
    if not isinstance(holder_conversation_id, str) or not holder_conversation_id:
        holder_conversation_id = holder_session_id
    if holder_conversation_id == arriving_conversation_id:
        return RemountDecision(
            REMOUNT_ABSENT,
            holder_session_id,
            holder_conversation_id,
            arriving_conversation_id,
        )
    sequence = record.get("holder_hook_sequence", 0)
    if not isinstance(sequence, int):
        sequence = 0
    candidate = record.get("candidate_conversation_id")
    if not isinstance(candidate, str) or not candidate:
        record.update(
            {
                "candidate_conversation_id": arriving_conversation_id,
                "candidate_observed_sequence": sequence,
                "candidate_seen_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        outcome = REMOUNT_OBSERVING if _write_record(path, record) else REMOUNT_REFUSED
        return RemountDecision(
            outcome,
            holder_session_id,
            holder_conversation_id,
            arriving_conversation_id,
        )
    baseline = record.get("candidate_observed_sequence", -1)
    if candidate != arriving_conversation_id or baseline != sequence:
        return RemountDecision(
            REMOUNT_REFUSED,
            holder_session_id,
            holder_conversation_id,
            arriving_conversation_id,
        )
    outcome = REMOUNT_CONTINUITY if _consume_live(path) else REMOUNT_REFUSED
    return RemountDecision(
        outcome,
        holder_session_id,
        holder_conversation_id,
        arriving_conversation_id,
    )


def remount_expect_is_live(map_dir: _MapDir, holder_session_id: str) -> bool:
    """True when a non-expired receipt exists for ``holder_session_id``."""
    path = _expect_path(map_dir, holder_session_id)
    if path is None:
        return False
    return _read_live(path) is not None


def _consume_live(path: Path) -> bool:
    if _read_live(path) is None:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def consume_remount_expect(map_dir: _MapDir, holder_session_id: str) -> bool:
    """Remove a live receipt. True only when one existed and was deleted."""
    if is_hook_replay():
        return False
    path = _expect_path(map_dir, holder_session_id)
    if path is None:
        return False
    with _exclusive_receipt(path) as locked:
        return locked and _consume_live(path)


__all__ = [
    "REMOUNT_ABSENT",
    "REMOUNT_CONTINUITY",
    "REMOUNT_EXPECT_DIR_NAME",
    "REMOUNT_EXPECT_TTL_S",
    "REMOUNT_OBSERVING",
    "REMOUNT_REFUSED",
    "REMOUNT_REFUSAL_PAYLOAD_FIELD",
    "RemountDecision",
    "consume_remount_expect",
    "is_remount_observation_event",
    "observe_remount_candidate",
    "remount_expect_is_live",
    "write_remount_expect",
]
