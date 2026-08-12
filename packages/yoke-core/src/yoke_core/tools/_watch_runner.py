"""Shared machinery for command-shaped watcher wrappers.

Watchers maintain two distinct output artifacts:

1. Raw capture file — byte-for-byte combined stdout/stderr from the
   underlying command. Every line lands here for post-failure
   inspection. Annotations and wrapper headers/footers are NEVER
   written to the raw capture — its contract is forensic fidelity.
2. Progress capture file — emitted lines (URGENT, SUMMARY, METADATA, and
   throttled PROGRESS), plus the wrapper's own metadata banner
   (header + footer) and any progress-line suppression annotations.
   This is the file Claude Monitor follows with ``watch_tail`` because
   the wrapper has already filtered, and it is also streamed to the
   wrapper's own stdout so direct (Codex / shell) callers see the same
   filtered progress.

Each command-shaped wrapper (``watch_pytest``, ``watch_merge``, ...)
ships only its line classifier — see
:mod:`yoke_core.tools._watch_throttle` for the class taxonomy.

Watched children inherit ``PYTHONUNBUFFERED=1``. Python otherwise block-
buffers stdout when the watcher replaces its terminal with a pipe, hiding
progress until the child exits.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Sequence, TextIO

from yoke_core.domain import process_group_reaping
from yoke_core.domain.project_scratch_dir import mint_watcher_capture_pair
from yoke_core.domain.session_liveness_pump import SessionLivenessPump

# Re-exported so wrappers keep importing one watcher entrypoint.
from yoke_core.tools._watch_streaming_pair import print_streaming_pair  # noqa: F401
from yoke_core.tools._watch_throttle import (
    Classification,
    LineClass,
    ProgressGate,
    ThrottlePolicy,
    annotate_progress_line,
    load_throttle_policy,
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


Classifier = Callable[[str], Classification]


def _unbuffered_child_environment(
    env: dict[str, str] | None,
) -> dict[str, str]:
    """Return an isolated child environment with immediate Python output."""
    source = os.environ if env is None else env
    return {**source, "PYTHONUNBUFFERED": "1"}


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


def filter_match(pattern: re.Pattern[str], line: str) -> bool:
    """Return True when *line* matches *pattern*.

    Retained for classifier authors that want to compose a class
    decision out of a regex pre-check. Line-oriented; callers compose
    the regex without ``re.MULTILINE``.
    """
    return bool(pattern.search(line))


def regex_classifier(pattern: re.Pattern[str]) -> Classifier:
    """Adapt a single regex into a classifier.

    Matching lines are classified as ``PROGRESS`` with no numeric value
    (time-window throttling only); non-matching lines are ``NOISE``.
    Provided so callers without a richer taxonomy can still benefit
    from the shared throttle gate.
    """

    def _classify(line: str) -> Classification:
        if pattern.search(line):
            return Classification(LineClass.PROGRESS)
        return Classification(LineClass.NOISE)

    return _classify


def _emit_immediate(
    line: str,
    *,
    progress_f: TextIO,
    out: TextIO,
) -> None:
    """Write a single line straight to progress capture and stdout."""
    progress_f.write(line)
    progress_f.flush()
    out.write(line)
    out.flush()


def _emit_progress(
    line: str,
    *,
    suppressed: int,
    progress_f: TextIO,
    out: TextIO,
) -> None:
    """Write a progress line, optionally annotated with suppression count."""
    rendered = annotate_progress_line(line, suppressed)
    progress_f.write(rendered)
    progress_f.flush()
    out.write(rendered)
    out.flush()


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
    footer_metadata: Callable[[], str | None] | None = None,
) -> int:
    """Run *argv* under the shared raw + throttled-progress contract.

    The classifier owns the per-line class decision. ``URGENT``,
    ``SUMMARY``, and ``METADATA`` lines emit immediately. ``PROGRESS``
    lines are routed through :class:`ProgressGate` for percent-step or
    time-window throttling. ``NOISE`` lines are written to raw only.

    ``stdout_stream`` is primarily a test seam — production callers leave it
    unset so the wrapper writes filtered progress to its own ``sys.stdout``.
    ``policy`` and ``time_source`` are optional test seams; production callers
    use the config-driven defaults. ``timeout_seconds`` starts when the watched
    child starts, not while a caller waits for an external admission gate.

    ``footer_metadata`` supplies wrapper-specific summary evidence after the
    child exits and before the exit sentinel. ``liveness`` keeps the session
    that started this command from going
    stale while it waits: a long gate run is activity, and without the
    refresh the stale-session sweep reclaims the item claim mid-run.
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
    deadline = clock() + timeout_seconds if timeout_seconds is not None else None

    header = (
        f"# watch_{kind} raw={raw_capture} "
        f"progress={progress_capture} "
        f"argv={shlex.join(argv)}\n"
    )

    raw_f = raw_capture.open("w", encoding="utf-8", buffering=1)
    progress_f = progress_capture.open("w", encoding="utf-8", buffering=1)

    try:
        # Wrapper metadata is class METADATA: emit immediately, never to raw.
        _emit_immediate(header, progress_f=progress_f, out=out)

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
            # Armed followers (watch_tail) exit only on the sentinel, so
            # the launch-error path must still write the exit footer.
            footer = f"# watch_{kind} exit={WRAPPER_LAUNCH_ERROR} raw={raw_capture}\n"
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
                    raw_f=raw_f,
                    progress_f=progress_f,
                    out=out,
                    emit_immediate=lambda line: _emit_immediate(
                        line, progress_f=progress_f, out=out
                    ),
                    emit_progress=lambda line, suppressed: _emit_progress(
                        line,
                        suppressed=suppressed,
                        progress_f=progress_f,
                        out=out,
                    ),
                    pump_tick=pump.tick,
                    clock=clock,
                    deadline=deadline,
                    timeout_seconds=timeout_seconds,
                    raw_capture=raw_capture,
                    stall_abort_exit=STALL_ABORT_EXIT,
                )
                if early is not None:
                    return early
                rc = TIMEOUT_EXIT if timed_out else proc.wait()
        except process_group_reaping.ProcessGroupInterrupted as interruption:
            # The guard has already reaped the child's whole group, so the
            # databases that group held are released before this returns. Say
            # so on every surface: an armed follower exits on the sentinel, and
            # a run that died silently is indistinguishable from one still going.
            rc = _EXIT_STATUS_SIGNAL_BASE + interruption.signal_number
            reaped = (
                f"# watch_{kind} interrupted by signal "
                f"{interruption.signal_number}; child process group reaped\n"
            )
            raw_f.write(reaped)
            _emit_immediate(reaped, progress_f=progress_f, out=out)
            footer = f"# watch_{kind} exit={rc} raw={raw_capture}\n"
            _emit_immediate(footer, progress_f=progress_f, out=out)
            return rc
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
