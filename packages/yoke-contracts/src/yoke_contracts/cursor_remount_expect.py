"""Short-lived receipt that a Cursor remount may alias onto a holder session.

Cursor remounts mint a new conversation id and do not send a parent id.
While the holder is still on the main checkout, each client hook refreshes
a receipt under ``{map_dir}/remount-expect/``. The first hook in the
linked worktree consumes that receipt before aliasing the new conversation
onto the holder. Folder occupancy alone is not enough.

Never raises — hook bookkeeping must not break a hook. Replay writes
nothing and consumes nothing.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union

from yoke_contracts.payload_session_fold import is_hook_replay


REMOUNT_EXPECT_DIR_NAME = "remount-expect"
REMOUNT_EXPECT_TTL_S = 300

# Same shape as the conversation-map filename guard: refuse rather than
# sanitize, so a reader never looks up a rewritten key.
_SAFE_ID = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")

_MapDir = Union[str, "os.PathLike[str]"]


def _expect_path(map_dir: _MapDir, holder_session_id: str) -> Optional[Path]:
    if not holder_session_id or not _SAFE_ID.match(holder_session_id):
        return None
    return Path(map_dir) / REMOUNT_EXPECT_DIR_NAME / f"{holder_session_id}.json"


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


def write_remount_expect(map_dir: _MapDir, holder_session_id: str) -> bool:
    """Refresh the holder's remount receipt. Returns whether it was written."""
    if is_hook_replay():
        return False
    path = _expect_path(map_dir, holder_session_id)
    if path is None:
        return False
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=REMOUNT_EXPECT_TTL_S)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "expires_at": expires.isoformat(),
                "holder_session_id": holder_session_id,
                "written_at": now.isoformat(),
            },
            sort_keys=True,
        )
        tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
        tmp.write_text(payload + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, ValueError):
        return False
    return True


def remount_expect_is_live(map_dir: _MapDir, holder_session_id: str) -> bool:
    """True when a non-expired receipt exists for ``holder_session_id``."""
    path = _expect_path(map_dir, holder_session_id)
    if path is None:
        return False
    return _read_live(path) is not None


def consume_remount_expect(map_dir: _MapDir, holder_session_id: str) -> bool:
    """Remove a live receipt. True only when one existed and was deleted."""
    if is_hook_replay():
        return False
    path = _expect_path(map_dir, holder_session_id)
    if path is None:
        return False
    if _read_live(path) is None:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


__all__ = [
    "REMOUNT_EXPECT_DIR_NAME",
    "REMOUNT_EXPECT_TTL_S",
    "consume_remount_expect",
    "remount_expect_is_live",
    "write_remount_expect",
]
