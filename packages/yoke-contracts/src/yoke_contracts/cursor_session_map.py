"""Map a Cursor conversation id to the session Yoke registered for it.

The third rung of the ambient-identity chain, for the one harness the
first two cannot reach. Cursor stamps no session-id environment variable
that :data:`~yoke_contracts.session_identity.AMBIENT_ENV_VARS` reads, and
one ``cursor-agent`` process hosts the main conversation plus every
subagent it dispatches — so the process-anchor registry correctly refuses
to anchor there, since a record keyed on that shared pid would resolve to
whichever sibling wrote last.

What a Cursor shell *does* carry is ``CURSOR_CONVERSATION_ID``: the
conversation that spawned it, which for a dispatched subagent is the
subagent's own id rather than the top-level session Yoke registered. A
bare conversation id is therefore not an identity — trusting it directly
would attribute subagent work to a session row that does not exist.

Cursor's hook processes see both ids at once: the payload names the
acting conversation, and the transcript path names the top-level
container. Each hook records that pair here, and a later shell resolves
its own conversation id through the recording — falling through
unresolved when no hook recorded it, rather than guessing.

Pure standard library and directory-injected, so the hook writer and the
CLI reader share one body — the same split, and for the same reason, as
:mod:`yoke_contracts.session_identity`.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Union


CURSOR_SESSION_MAP_DIR_NAME = "cursor-session-map"

CURSOR_CONVERSATION_ENV_VAR = "CURSOR_CONVERSATION_ID"

# A conversation outlives any single hook, so entries are kept for far
# longer than the model spool's seconds-long hand-off. The cap exists so a
# machine running Cursor for months does not accumulate a record per
# conversation forever, and so a recycled id can never resolve to an
# ancient session.
_STALE_AGE_S = 7 * 24 * 3600

# Conversation ids are uuid-shaped. Anything else is refused rather than
# sanitized: an id that cannot be a filename is an id we did not receive
# from Cursor, and quietly rewriting it would key the entry on something
# the reader will never ask for.
_SAFE_ID = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")

_MapDir = Union[str, "os.PathLike[str]"]


def _entry_path(map_dir: _MapDir, conversation_id: str) -> Optional[Path]:
    if not conversation_id or not _SAFE_ID.match(conversation_id):
        return None
    return Path(map_dir) / f"{conversation_id}.json"


def record_conversation_session(
    conversation_id: str,
    session_id: str,
    map_dir: _MapDir,
) -> bool:
    """Record that ``conversation_id`` belongs to ``session_id``.

    Returns whether the pairing was written. Never raises — a hook must
    not fail on a bookkeeping file. Rewriting on every hook is deliberate:
    it keeps the entry's mtime fresh for the staleness cap, and it costs
    one small atomic write beside work the hook is already doing.
    """
    path = _entry_path(map_dir, conversation_id)
    if path is None or not session_id:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "session_id": session_id,
                "conversation_id": conversation_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=True,
        )
        tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
        tmp.write_text(payload + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, ValueError):
        return False
    return True


def resolve_mapped_session_id(
    map_dir: _MapDir,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Resolve this process's session from its Cursor conversation id.

    ``None`` when the process carries no conversation id, when no hook has
    recorded that conversation, or when the recording has aged out — every
    one of which is a truthful "unknown", and a better answer than the
    conversation id itself. Never raises.
    """
    source = os.environ if env is None else env
    conversation_id = (source.get(CURSOR_CONVERSATION_ENV_VAR) or "").strip()
    path = _entry_path(map_dir, conversation_id)
    if path is None:
        return None
    try:
        if path.stat().st_mtime < time.time() - _STALE_AGE_S:
            path.unlink(missing_ok=True)
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    session_id = record.get("session_id")
    return session_id if isinstance(session_id, str) and session_id else None


def prune_stale_conversation_sessions(map_dir: _MapDir) -> int:
    """Drop recordings past the staleness cap. Returns how many were removed.

    Best-effort maintenance for the same session-start sweep that prunes
    the anchor registry; resolution already ages out the single entry it
    reads, so a missed sweep only leaves disk behind. Never raises.
    """
    removed = 0
    cutoff = time.time() - _STALE_AGE_S
    try:
        for entry in Path(map_dir).glob("*.json"):
            try:
                if entry.stat().st_mtime >= cutoff:
                    continue
                entry.unlink(missing_ok=True)
            except OSError:
                continue
            removed += 1
    except OSError:
        return removed
    return removed


__all__ = [
    "CURSOR_CONVERSATION_ENV_VAR",
    "CURSOR_SESSION_MAP_DIR_NAME",
    "prune_stale_conversation_sessions",
    "record_conversation_session",
    "resolve_mapped_session_id",
]
