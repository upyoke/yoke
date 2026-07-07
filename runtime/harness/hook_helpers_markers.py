"""Current-item / done-item marker file primitives for hook owners.

The legacy current-item marker file was retired when DB-backed
``harness_sessions.current_item`` lookups replaced marker-based
attribution. The marker constants and read/write helpers remain to
support transitional callers and the existing event-tracking code
paths until every caller is migrated to the DB-backed lookup.

The marker file paths are resolved through
``yoke_core.domain.project_scratch_dir.hook_marker_path`` so the
scratch root is controlled by one resolver (env / config /
``$TMPDIR`` fallback) across the codebase.
"""

from __future__ import annotations

import time

from yoke_core.domain.project_scratch_dir import hook_marker_path


CURRENT_ITEM_MARKER = str(hook_marker_path("current-item"))
DONE_ITEM_MARKER = str(hook_marker_path("done-item"))
DEFAULT_DONE_MARKER_MAX_AGE = 1800  # 30 minutes


def write_current_item_marker(item_id: int | str) -> None:
    """Write the current-item marker with the numeric item ID."""
    if not item_id:
        return
    try:
        with open(CURRENT_ITEM_MARKER, "w") as f:
            f.write(f"{item_id}\n")
    except OSError:
        pass


def read_current_item_marker() -> str:
    """Read the current-item marker. Returns empty string if missing."""
    try:
        with open(CURRENT_ITEM_MARKER) as f:
            return f.read().strip()
    except OSError:
        return ""


def write_done_item_marker(item_id: int | str) -> None:
    """Write the done-item marker with ``item_id|epoch``."""
    if not item_id:
        return
    try:
        epoch = int(time.time())
        with open(DONE_ITEM_MARKER, "w") as f:
            f.write(f"{item_id}|{epoch}\n")
    except OSError:
        pass


def read_done_item_marker(
    max_age: int = DEFAULT_DONE_MARKER_MAX_AGE,
) -> str:
    """Read the done-item marker if recent. Returns empty string if expired/missing."""
    try:
        with open(DONE_ITEM_MARKER) as f:
            line = f.read().strip()
        if "|" not in line:
            return ""
        item_id, ts_str = line.split("|", 1)
        if not item_id or not ts_str:
            return ""
        ts = int(ts_str)
        age = int(time.time()) - ts
        if 0 <= age <= max_age:
            return item_id
        return ""
    except (OSError, ValueError):
        return ""
