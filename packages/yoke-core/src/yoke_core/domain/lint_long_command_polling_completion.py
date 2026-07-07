"""Watcher-completion detection for the long-command polling lint.

Split sibling of :mod:`lint_long_command_polling_evaluate`. Owns the
"has the watcher that owns this capture file already exited?" signal that
distinguishes a genuinely-completed background command from a still-
running one — the gap that made the single sanctioned post-completion
inspection (``tail -80 <raw-capture>``) get denied as a mid-run progress
peek (ouroboros 8857 / 8873).

Lives in a dedicated module so the evaluate sibling stays under the
350-line authored-file cap (``HC-file-line-limit``).

Detection model:

Yoke's watcher wrappers (``watch_pytest`` / ``watch_merge`` /
``watch_doctor`` / ...) write a ``# watch_<kind> exit=<rc>`` sentinel as
the FINAL line of the PROGRESS capture when the underlying command exits
(see :func:`yoke_core.tools._watch_runner.run_watcher`). The RAW
capture deliberately omits the sentinel — its contract is byte-for-byte
forensic fidelity — so for a raw-capture peek the sentinel lives in the
sibling progress file (``.raw.`` -> ``.progress.``, the inverse of
:func:`lint_long_command_polling_decide._raw_capture_hint`).

The sentinel is the authoritative completion signal: the evaluate
sibling's mtime heuristic cannot tell a just-finished command (its final
output was just written, so the mtime is recent) from a still-running
one. Once the sentinel is present the owning command has exited and the
post-capture peek is allowed without a suppression token. While the
command is still running there is no sentinel, so the caller falls back
to mtime and a genuine mid-run peek is still denied.
"""

from __future__ import annotations

import os

__all__ = ["capture_file_completed"]

# Read at most this many trailing bytes of a watcher capture when scanning
# for the exit sentinel. The sentinel is always the wrapper's final line, so
# the tail is sufficient and bounds the read on large (multi-MB) captures.
_SENTINEL_TAIL_BYTES = 8192


def _watcher_exit_sentinel_pattern():
    """Return the canonical watcher exit-sentinel regex, or ``None``.

    Single source of truth is
    :data:`yoke_core.tools.watch_tail.EXIT_SENTINEL` — the same
    ``^# watch_<kind> exit=<rc>`` pattern the Monitor-side follower
    matches to auto-exit. Imported lazily (and tolerantly) so the lint
    never hard-depends on the tools package at module-load time and
    degrades to the mtime heuristic if the import is ever unavailable.
    """
    try:
        from yoke_core.tools.watch_tail import EXIT_SENTINEL
    except Exception:
        return None
    return EXIT_SENTINEL


def _file_has_exit_sentinel(path: str) -> bool:
    """Return True when *path*'s tail carries a watcher exit-sentinel line.

    Reads only the last :data:`_SENTINEL_TAIL_BYTES` bytes — the sentinel
    is the wrapper's final line. Any read error (missing file, unreadable)
    yields ``False`` so the caller degrades to the mtime heuristic.
    """
    sentinel = _watcher_exit_sentinel_pattern()
    if sentinel is None:
        return False
    try:
        with open(path, "rb") as handle:
            try:
                handle.seek(-_SENTINEL_TAIL_BYTES, os.SEEK_END)
            except OSError:
                handle.seek(0)
            tail = handle.read()
    except OSError:
        return False
    for line in tail.decode("utf-8", errors="replace").splitlines():
        if sentinel.match(line):
            return True
    return False


def capture_file_completed(capture_file: str) -> bool:
    """Return True when the watcher that owns *capture_file* has exited.

    For a raw-capture peek (``.raw.`` in the path) the sentinel lives in
    the sibling progress file, so derive ``.progress.`` and check there;
    checking the raw file would risk a false positive from command output
    that happens to look like a sentinel line. For a direct progress-
    capture peek (or an unpaired capture) the sentinel, if any, is in the
    file itself.
    """
    if ".raw." in capture_file:
        return _file_has_exit_sentinel(
            capture_file.replace(".raw.", ".progress.", 1)
        )
    return _file_has_exit_sentinel(capture_file)
