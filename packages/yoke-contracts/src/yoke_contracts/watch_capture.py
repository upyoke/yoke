"""Whether a watcher capture file's owning command is still running.

Yoke's watcher wrappers (``yoke watch pytest`` and its siblings) write a
``# watch_<kind> exit=<rc>`` sentinel as the FINAL line of the PROGRESS
capture when the underlying command exits. The RAW capture deliberately
omits it — its contract is byte-for-byte forensic fidelity — so for a raw
capture the sentinel lives in the sibling progress file (``.raw.`` ->
``.progress.``).

The sentinel is the authoritative completion signal. Without it, a capture
touched recently is still being appended to. Only the machine that wrote the
capture can read it, so the hook client observes :func:`capture_state` and
ships it as a client fact; the polling policy reads that fact.
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional

#: The wrapper footer ``yoke_core.tools._watch_runner.run_watcher`` writes.
#: The rc may be negative (signal-killed child, e.g. ``exit=-15``).
EXIT_SENTINEL = re.compile(r"^# watch_\w+ exit=-?\d+")

# The sentinel is always the wrapper's final line, so the tail is enough and
# bounds the read on large (multi-MB) captures.
_SENTINEL_TAIL_BYTES = 8192


def _file_has_exit_sentinel(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            try:
                handle.seek(-_SENTINEL_TAIL_BYTES, os.SEEK_END)
            except OSError:
                handle.seek(0)
            tail = handle.read()
    except OSError:
        return False
    return any(
        EXIT_SENTINEL.match(line)
        for line in tail.decode("utf-8", errors="replace").splitlines()
    )


def capture_file_completed(capture_file: str) -> bool:
    """Return True when the watcher that owns *capture_file* has exited."""
    if ".raw." in capture_file:
        return _file_has_exit_sentinel(capture_file.replace(".raw.", ".progress.", 1))
    return _file_has_exit_sentinel(capture_file)


def capture_state(capture_file: str, *, now: Optional[float] = None) -> dict:
    """Return ``{"completed": bool, "age_seconds": float | None}``.

    ``age_seconds`` is the time since the capture was last written, or
    ``None`` when the file does not exist on this machine.
    """
    completed = capture_file_completed(capture_file)
    try:
        mtime = os.stat(capture_file).st_mtime
    except OSError:
        return {"completed": completed, "age_seconds": None}
    current = time.time() if now is None else now
    return {"completed": completed, "age_seconds": max(0.0, current - mtime)}


__all__ = ["EXIT_SENTINEL", "capture_file_completed", "capture_state"]
