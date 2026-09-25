"""Shared machinery for command-shaped watcher wrappers.

Watchers maintain two distinct output artifacts:

1. Raw capture file — byte-for-byte combined stdout/stderr from the
   underlying command. Every line lands here for post-failure
   inspection. Annotations and wrapper headers/footers are NEVER
   written to the raw capture — its contract is forensic fidelity.
2. Progress capture file — either the standard immediate tiers and
   digested progress, or an outcome-only stream for merge and deploy.
   ``watch_tail`` follows this already-filtered file; direct callers see
   the same stream on wrapper stdout.

Each command-shaped wrapper (``watch_pytest``, ``watch_merge``, ...)
ships only its line classifier — see
:mod:`yoke_core.tools._watch_throttle` for the class taxonomy and
:mod:`yoke_core.tools._watch_digest` for the batching window.

Watched children inherit ``PYTHONUNBUFFERED=1``. Python otherwise block-
buffers stdout when the watcher replaces its terminal with a pipe, hiding
progress until the child exits.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Sequence, TextIO

from yoke_core.domain import process_group_reaping
from yoke_core.domain.session_liveness_pump import SessionLivenessPump

# Re-exported so wrappers keep importing one watcher entrypoint.
from yoke_core.tools._watch_capture_binding import (  # noqa: F401
    bind_capture_paths,
    mint_capture_paths,
    misplaced_capture_flags,
    misplaced_capture_rejection,
    note_claimed_capture,
    refuse_claimed_capture,
)
from yoke_core.tools._watch_streaming_pair import (  # noqa: F401
    STREAMING_WAIT_HELP,
    print_in_turn_invocation,
    print_streaming_pair,
    print_wait_mode_invocation,
)
from yoke_core.tools._watch_output import (
    emit_immediate as _emit_immediate,
    emit_watcher_header,
    unbuffered_child_environment as _unbuffered_child_environment,
)
from yoke_core.tools._watch_digest import (  # noqa: F401
    DEFAULT_FLUSH_SECONDS,
    ProgressDigest,
)
from yoke_core.tools._watch_terminal_outcome import (
    emit_terminal_outcome,
    terminal_error_from_raw_capture,
)
from yoke_core.tools._watch_throttle import (  # noqa: F401
    Classification,
    Classifier,
    LineClass,
    ProgressGate,
    ThrottlePolicy,
    annotate_progress_line,
    filter_match,
    load_throttle_policy,
    regex_classifier,
)
from yoke_core.tools.watch_child_drain import (
    QUIET_HEARTBEAT_SECONDS_ENV,  # noqa: F401 - watcher test/config surface
    drain_watched_child,
)

# Wrapper-level error code: the wrapper itself failed to launch the
# underlying command (e.g., binary missing). Distinct from a successful
# launch where the command exits non-zero.
WRAPPER_LAUNCH_ERROR = 127
#: Shell convention for "died on signal N": callers reading the exit code see
#: 130 for Ctrl-C and 143 for SIGTERM rather than an ambiguous generic failure.
_EXIT_STATUS_SIGNAL_BASE = 128
#: ``timeout(1)``'s convention for "the deadline expired". Named so callers
#: that must recognise a timed-out run do not restate the number.
TIMEOUT_EXIT = 124
STALL_ABORT_EXIT = 125  # nested-admission deadlock; capture names the reason
PRINT_STREAMING_PAIR_FLAG = "--print-streaming-pair"


def run_watcher(
    *,
    argv: Sequence[str],
    classifier: Classifier,
    raw_capture: Path,
    progress_capture: Path,
    kind: str,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdout_stream: Optional[TextIO] = None,
    policy: Optional[ThrottlePolicy] = None,
    time_source: Optional[Callable[[], float]] = None,
    timeout_seconds: float | None = None,
    liveness: Optional[SessionLivenessPump] = None,
    header_metadata: str | None = None,
    footer_metadata: Callable[[], str | None] | None = None,
    flush_seconds: float = DEFAULT_FLUSH_SECONDS,
    digest_label: str | None = None,
    outcome_only: bool = False,
) -> int:
    """Run *argv* under the shared capture and user-facing output contract.

    The classifier owns each line's class. Standard watchers immediately
    emit urgent, summary, and metadata lines, digest progress, and retain
    noise in raw. Outcome-only watchers immediately emit urgent lines,
    defer summaries until a zero exit, and keep all routine lines in raw.

    ``digest_label`` names the run inside its digest lines, so a seat
    driving two of them can tell the two apart in one transcript.

    ``stdout_stream`` is primarily a test seam — production callers leave it
    unset so the wrapper writes its filtered stream to ``sys.stdout``.
    ``policy`` and ``time_source`` are optional test seams; production callers
    use the config-driven defaults. ``timeout_seconds`` starts when the watched
    child starts, not while a caller waits for an external admission gate.

    ``header_metadata`` and ``footer_metadata`` supply wrapper-specific
    evidence around the child run. ``liveness`` keeps the session
    that started this command from going
    stale while it waits: a long gate run is activity, and without the
    refresh a claimless session can age out mid-run; an active work claim
    remains protected independently of the heartbeat.

    ``outcome_only`` suppresses watcher metadata and routine progress,
    defers summaries until a zero child exit, and reports a final result
    with the raw-capture path on either outcome.
    """
    out: TextIO = stdout_stream or sys.stdout
    pump = liveness if liveness is not None else SessionLivenessPump()

    raw_capture.parent.mkdir(parents=True, exist_ok=True)
    progress_capture.parent.mkdir(parents=True, exist_ok=True)

    if policy is None:
        policy = load_throttle_policy()
    gate = (
        ProgressGate(policy, time_source=time_source)
        if time_source is not None
        else ProgressGate(policy)
    )
    clock = time_source or time.monotonic
    digest = ProgressDigest(
        kind=kind,
        label=digest_label,
        flush_seconds=flush_seconds,
        time_source=clock,
    )
    deadline = clock() + timeout_seconds if timeout_seconds is not None else None

    raw_f = raw_capture.open("w", encoding="utf-8", buffering=1)
    # Appended, not truncated: ``bind_capture_paths`` has already stamped
    # this process's ownership marker as the file's first line, and a
    # follower may already be reading past it. Truncating here would both
    # drop the marker and strand that reader beyond a shortened file.
    progress_f = progress_capture.open("a", encoding="utf-8", buffering=1)

    def flush_digest() -> None:
        """Release buffered progress ahead of whatever is written next."""
        carried = digest.flush()
        if carried is not None:
            _emit_immediate(carried, progress_f=progress_f, out=out)

    try:
        emit_watcher_header(
            kind=kind,
            raw_capture=raw_capture,
            progress_capture=progress_capture,
            argv=argv,
            progress_f=progress_f,
            out=out,
            outcome_only=outcome_only,
            header_metadata=header_metadata,
        )

        try:
            # A watched run is the one most likely to be interrupted, and its
            # children (xdist workers) hold the databases. Own the whole group
            # so an interruption can reap every descendant, not just pytest.
            proc = process_group_reaping.popen_in_process_group(
                list(argv),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                cwd=cwd,
                env=_unbuffered_child_environment(env),
            )
        except (FileNotFoundError, OSError) as exc:
            err_line = f"# watch_{kind} launch_error: {exc}\n"
            # Launch errors must reach all surfaces, including raw.
            raw_f.write(err_line)
            _emit_immediate(err_line, progress_f=progress_f, out=out)
            if outcome_only:
                emit_terminal_outcome(
                    kind=kind,
                    exit_code=WRAPPER_LAUNCH_ERROR,
                    raw_capture=raw_capture,
                    raw_f=raw_f,
                    progress_f=progress_f,
                    out=out,
                )
            else:
                footer = (
                    f"# watch_{kind} exit={WRAPPER_LAUNCH_ERROR} raw={raw_capture}\n"
                )
                _emit_immediate(footer, progress_f=progress_f, out=out)
            return WRAPPER_LAUNCH_ERROR

        assert proc.stdout is not None
        try:
            with process_group_reaping.interruption_reaps_process_group(proc):
                early, last_summary, timed_out = drain_watched_child(
                    proc=proc,
                    kind=kind,
                    classifier=classifier,
                    gate=gate,
                    digest=digest,
                    raw_f=raw_f,
                    progress_f=progress_f,
                    out=out,
                    emit_immediate=lambda line: _emit_immediate(
                        line, progress_f=progress_f, out=out
                    ),
                    pump_tick=pump.tick,
                    clock=clock,
                    deadline=deadline,
                    timeout_seconds=timeout_seconds,
                    raw_capture=raw_capture,
                    stall_abort_exit=STALL_ABORT_EXIT,
                    outcome_only=outcome_only,
                )
                if early is not None:
                    if outcome_only:
                        emit_terminal_outcome(
                            kind=kind,
                            exit_code=early,
                            raw_capture=raw_capture,
                            raw_f=raw_f,
                            progress_f=progress_f,
                            out=out,
                        )
                    return early
                rc = TIMEOUT_EXIT if timed_out else proc.wait()
        except process_group_reaping.ProcessGroupInterrupted as interruption:
            # The guard has already reaped the child's whole group, so the
            # databases that group held are released before this returns. Say
            # so on every surface: an armed follower exits on the sentinel, and
            # a run that died silently is indistinguishable from one still going.
            rc = _EXIT_STATUS_SIGNAL_BASE + interruption.signal_number
            flush_digest()
            reaped = (
                f"# watch_{kind} interrupted by signal "
                f"{interruption.signal_number}; child process group reaped\n"
            )
            raw_f.write(reaped)
            _emit_immediate(reaped, progress_f=progress_f, out=out)
            if outcome_only:
                emit_terminal_outcome(
                    kind=kind,
                    exit_code=rc,
                    raw_capture=raw_capture,
                    raw_f=raw_f,
                    progress_f=progress_f,
                    out=out,
                )
            else:
                footer = f"# watch_{kind} exit={rc} raw={raw_capture}\n"
                _emit_immediate(footer, progress_f=progress_f, out=out)
            return rc
        # Completion always flushes: a run that ended mid-window still
        # owes the follower the motion it accumulated.
        if outcome_only:
            emit_terminal_outcome(
                kind=kind,
                exit_code=rc,
                raw_capture=raw_capture,
                raw_f=raw_f,
                progress_f=progress_f,
                out=out,
                result_summary=last_summary,
            )
            return rc
        else:
            flush_digest()
            if rc:
                raw_f.flush()
                terminal_error = terminal_error_from_raw_capture(raw_capture)
                if terminal_error:
                    _emit_immediate(
                        f"# watch_{kind} error: {terminal_error}\n",
                        progress_f=progress_f,
                        out=out,
                    )
        # Re-emit the last SUMMARY line as an explicit terminal footer
        # before the exit sentinel. Mid-stream SUMMARY emits go through
        # `_emit_immediate` above, but agents reading the tail of the
        # progress capture after the task completes can miss them
        # (Monitor exits when the bg task completes, the final SUMMARY
        # may be visually buried under PROGRESS ticks emitted just
        # before it, or the last few wake events may be consumed before
        # the agent processes them). The explicit footer gives a
        # deterministic, machine-parseable verdict line at a fixed
        # location: the second-to-last line of the progress capture,
        # immediately before the `# watch_<kind> exit=<rc>` sentinel.
        if last_summary is not None:
            summary_footer = f"# watch_{kind} summary: {last_summary.rstrip()}\n"
            _emit_immediate(summary_footer, progress_f=progress_f, out=out)
        if footer_metadata is not None:
            metadata = footer_metadata()
            if metadata:
                line = metadata if metadata.endswith("\n") else f"{metadata}\n"
                _emit_immediate(line, progress_f=progress_f, out=out)
        footer_extras = ""
        if gate.total_suppressed > 0:
            footer_extras = (
                f" suppressed_total={gate.total_suppressed}"
                f" suppressed_pending={gate.pending_suppressed}"
            )
        footer = f"# watch_{kind} exit={rc} raw={raw_capture}{footer_extras}\n"
        _emit_immediate(footer, progress_f=progress_f, out=out)
        return rc
    finally:
        raw_f.close()
        progress_f.close()
