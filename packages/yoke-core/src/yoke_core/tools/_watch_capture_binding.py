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

For the same reason a wrapper binds before its own preflight, not after
it: an impacted-test selection, a control-plane lookup, or an import
probe can each outlast the follower's grace window, and an unclaimed
capture during that work is indistinguishable from one no run will ever
write. Binding first makes every refusal after it a close as well, which
is what :func:`refuse_claimed_capture` exists to do.

Imports stay limited to the scratch-path helper: ``watch_tail`` reads
this module, and reaching back into the watcher runtime from here would
close an import cycle through the streaming-pair renderer.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from yoke_core.domain.project_scratch_dir import mint_watcher_capture_pair

#: First line a bound watcher writes into its progress capture. The
#: producer (:func:`stamp_writer`) and the consumer (:func:`writer_pid`)
#: are the only two sides of this literal.
WRITER_MARKER_RE = re.compile(r"^# watch_\w+ writer_pid=(\d+)\b")
#: How long a follower waits for any writer evidence before refusing.
#: Covers interpreter start-up and the gap between arming the follower
#: and pasting the background command; a queued run has already stamped.
DEFAULT_WRITER_GRACE_SECONDS = 30.0
#: The wrapper flags naming the capture pair. A caller who places one
#: after the ``--`` separator hands it to the watched command, which
#: fails on the unknown option before it starts.
CAPTURE_FLAGS = ("--raw-capture", "--progress-capture")
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


def note_claimed_capture(progress_capture: Path | None, text: str) -> None:
    """Append one wrapper metadata line to an already-claimed capture.

    A wrapper claims its capture before its own preflight, so anything
    slow that runs before the watched command starts owes the follower a
    line saying so; silence and death read identically otherwise.
    """
    if progress_capture is None:
        return
    with progress_capture.open("a", encoding="utf-8") as handle:
        handle.write(f"{text.rstrip()}\n")


def refuse_claimed_capture(
    progress_capture: Path | None,
    kind: str,
    message: str,
    exit_code: int,
) -> int:
    """Report *message* and release any follower armed on the capture.

    Claiming a capture before preflight makes every later refusal a
    close as well: a follower reads writer liveness, so a wrapper that
    refuses and exits without a sentinel leaves that follower reporting
    a dead watcher instead of the refusal the operator has to act on.
    Writes the refusal and the exit sentinel
    :func:`yoke_core.tools._watch_runner.run_watcher` would otherwise
    have written, then returns *exit_code* so a refusal site stays one
    ``return`` statement.

    ``progress_capture`` is ``None`` on a path that never claimed one --
    ``--print-streaming-pair``, or a refusal raised before the claim --
    and the capture write is then skipped.
    """
    print(message, file=sys.stderr)
    note_claimed_capture(progress_capture, message)
    if progress_capture is not None:
        with progress_capture.open("a", encoding="utf-8") as handle:
            handle.write(f"# watch_{kind} exit={exit_code}\n")
    return exit_code


def misplaced_capture_flags(args: Sequence[str]) -> dict[str, Path]:
    """Capture flags a caller placed after the ``--`` separator.

    Each is returned with the path it named so the wrapper can claim
    that capture and refuse INTO it: a follower is already armed on the
    file the caller wrote down, and a refusal delivered anywhere else
    leaves that follower waiting on a run which never starts.
    """
    found: dict[str, Path] = {}
    for index, arg in enumerate(args):
        name, separator, inline = arg.partition("=")
        if name not in CAPTURE_FLAGS or name in found:
            continue
        following = args[index + 1] if index + 1 < len(args) else ""
        value = inline if separator else following
        if value and not value.startswith("-"):
            found[name] = Path(value)
    return found


def misplaced_capture_rejection(flags: Iterable[str], *, command: str) -> str:
    """Return the refusal naming the canonical position for *flags*."""
    return (
        f"{command}: wrapper capture flags after the '--' separator: "
        f"{', '.join(sorted(flags))}.\n"
        "They belong to the wrapper, not to the watched command, which "
        "takes them as unknown options and fails before it starts.\n"
        "Canonical position — before the separator:\n"
        f"  {command} --raw-capture RAW --progress-capture PROGRESS "
        "-- <args>\n"
        "The --print-streaming-pair background command already places them "
        "there; paste it verbatim."
    )
