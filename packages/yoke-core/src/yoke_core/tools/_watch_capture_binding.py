"""Binding between a watcher run and the capture pair a follower reads.

A watcher writes two capture files and a follower (``watch_tail``) reads
the progress one. Nothing in the file's own bytes says which process is
writing it, so a follower armed on a capture the run never used waits
forever on a file nobody writes: the run's exit sentinel lands in a
different file, and the wait looks identical to a slow command.

This module owns both halves of the binding so the two sides cannot
drift:

- the producer resolves its capture pair once and stamps its own pid
  into the progress capture as that file's first line, and
- the follower reads that marker to tell a live writer from a capture
  nobody writes, and refuses instead of waiting when there is neither.

The marker is stamped when the pair is bound rather than when the
watched command starts, because a wrapper can legitimately wait minutes
between the two -- the pytest admission gate is the worked case -- and
a follower that could not see an owner during that wait would refuse a
run that is merely queued.

Imports stay limited to the scratch-path helper: ``watch_tail`` reads
this module, and reaching back into the watcher runtime from here would
close an import cycle through the streaming-pair renderer.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from yoke_core.domain.project_scratch_dir import mint_watcher_capture_pair

#: First line a bound watcher writes into its progress capture. The
#: producer (:func:`stamp_writer`) and the consumer (:func:`writer_pid`)
#: are the only two sides of this literal.
WRITER_MARKER_RE = re.compile(r"^# watch_\w+ writer_pid=(\d+)\b")
#: How long a follower waits for any writer evidence before refusing.
#: Covers interpreter start-up and the gap between arming the follower
#: and pasting the background command; a queued run has already stamped.
DEFAULT_WRITER_GRACE_SECONDS = 30.0
#: Follower exit code for "this capture has no writer". Distinct from
#: argparse's ``2`` and from any watched command's own exit code, which
#: reaches a follower only through the sentinel line.
UNWRITTEN_CAPTURE_EXIT = 3


def writer_marker_line(kind: str, *, pid: int | None = None) -> str:
    """Return the ownership marker line for *kind* and *pid*."""
    return f"# watch_{kind} writer_pid={os.getpid() if pid is None else pid}\n"


def mint_capture_paths(kind: str) -> tuple[Path, Path]:
    """Mint ``(raw, progress)`` capture file paths under the scratch root.

    Thin wrapper over
    :func:`yoke_core.domain.project_scratch_dir.mint_watcher_capture_pair`
    so every watcher writes captures into the project-scoped
    ``watcher-captures`` subdir with a shared nonce linking the raw and
    progress files. Both files are created empty so downstream callers
    that ``stat`` the path before opening it observe an existing file.
    """
    raw_path, progress_path = mint_watcher_capture_pair(kind)
    raw_path.touch()
    progress_path.touch()
    return raw_path, progress_path


def stamp_writer(progress_capture: Path, kind: str) -> None:
    """Claim *progress_capture* for this process.

    Truncating write: the marker must be the file's first line so a
    follower reading from the beginning sees the owner before any
    progress content.
    """
    progress_capture.parent.mkdir(parents=True, exist_ok=True)
    progress_capture.write_text(writer_marker_line(kind), encoding="utf-8")


def bind_capture_paths(namespace: Any, kind: str) -> tuple[Path, Path]:
    """Resolve a wrapper run's capture pair and claim the progress file.

    Operator-supplied ``--raw-capture`` / ``--progress-capture`` values
    win; whichever is absent is minted. The pair a caller pastes from
    ``--print-streaming-pair`` arrives through those flags, which is
    exactly what binds the run to the follower already watching them.
    """
    raw = getattr(namespace, "raw_capture", None)
    progress = getattr(namespace, "progress_capture", None)
    if raw is None or progress is None:
        minted_raw, minted_progress = mint_capture_paths(kind)
        raw = raw or minted_raw
        progress = progress or minted_progress
    stamp_writer(progress, kind)
    return raw, progress


def writer_pid(line: str) -> int | None:
    """Return the pid claimed by *line*, or ``None`` when it is not a marker."""
    match = WRITER_MARKER_RE.match(line)
    return int(match.group(1)) if match else None


def writer_alive(pid: int) -> bool:
    """Return whether *pid* still names a live process on this machine.

    ``PermissionError`` means the process exists under another user, so
    it counts as alive; only ``ProcessLookupError`` proves it is gone.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def unwritten_capture_refusal(path: Path, *, grace_seconds: float) -> str:
    """Return the refusal for a capture no writer ever claimed."""
    return (
        f"# watch_tail refusing: no watcher claimed {path} within "
        f"{grace_seconds:g}s, and nothing has been written to it.\n"
        "#   Cause: this tail was armed on a capture the run never used. A "
        "wrapper run WITHOUT\n"
        "#   --raw-capture/--progress-capture mints a fresh capture pair and "
        "writes there instead.\n"
        "#   Fix: paste the background command from --print-streaming-pair "
        "verbatim -- its\n"
        "#   --raw-capture/--progress-capture flags are what bind the run to "
        "this tail -- then\n"
        "#   arm this tail once against the printed progress capture.\n"
    )


def dead_writer_refusal(path: Path, *, pid: int) -> str:
    """Return the refusal for a writer that died before its sentinel."""
    return (
        f"# watch_tail refusing: watcher pid {pid} owning {path} exited "
        "without writing an exit sentinel.\n"
        "#   Cause: the watcher process died before it could report "
        "'# watch_<kind> exit=<rc>'.\n"
        "#   Fix: inspect the raw capture named in this file's header line, "
        "then re-run the\n"
        "#   background command printed by --print-streaming-pair.\n"
    )
