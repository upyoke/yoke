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

``print_streaming_pair`` lives in
:mod:`yoke_core.tools._watch_streaming_pair` and is re-exported here so
wrappers keep reaching it through the runner.
"""

from __future__ import annotations

import os
import re
import selectors
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence, TextIO

from yoke_core.domain.project_scratch_dir import mint_watcher_capture_pair
from yoke_core.tools._watch_streaming_pair import print_streaming_pair
from yoke_core.tools._watch_throttle import (
    Classification,
    LineClass,
    ProgressGate,
    ThrottlePolicy,
    annotate_progress_line,
    load_throttle_policy,
)

# Wrapper-level error code: the wrapper itself failed to launch the
# underlying command (e.g., binary missing). Distinct from a successful
# launch where the command exits non-zero.
WRAPPER_LAUNCH_ERROR = 127
PRINT_STREAMING_PAIR_FLAG = "--print-streaming-pair"
QUIET_HEARTBEAT_SECONDS_ENV = "YOKE_WATCH_QUIET_HEARTBEAT_SECONDS"


Classifier = Callable[[str], Classification]


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
) -> int:
    """Run *argv* under the shared raw + throttled-progress contract.

    The classifier owns the per-line class decision. ``URGENT``,
    ``SUMMARY``, and ``METADATA`` lines emit immediately. ``PROGRESS``
    lines are routed through :class:`ProgressGate` for percent-step or
    time-window throttling. ``NOISE`` lines are written to raw only.

    ``stdout_stream`` is primarily a test seam — production callers
    leave it unset so the wrapper writes filtered progress to its own
    ``sys.stdout``. ``policy`` and ``time_source`` are optional test
    seams; production callers use the config-driven defaults.
    """
    out: TextIO = stdout_stream or sys.stdout

    raw_capture.parent.mkdir(parents=True, exist_ok=True)
    progress_capture.parent.mkdir(parents=True, exist_ok=True)

    if policy is None:
        policy = load_throttle_policy()
    gate = (
        ProgressGate(policy, time_source=time_source)
        if time_source is not None
        else ProgressGate(policy)
    )

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
            proc = subprocess.Popen(
                list(argv),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                cwd=cwd,
                env=env,
            )
        except (FileNotFoundError, OSError) as exc:
            err_line = f"# watch_{kind} launch_error: {exc}\n"
            # Launch errors must reach all surfaces, including raw.
            raw_f.write(err_line)
            _emit_immediate(err_line, progress_f=progress_f, out=out)
            # Armed followers (watch_tail) exit only on the sentinel, so
            # the launch-error path must still write the exit footer.
            footer = (
                f"# watch_{kind} exit={WRAPPER_LAUNCH_ERROR} "
                f"raw={raw_capture}\n"
            )
            _emit_immediate(footer, progress_f=progress_f, out=out)
            return WRAPPER_LAUNCH_ERROR

        assert proc.stdout is not None
        last_summary: Optional[str] = None
        quiet_seconds = float(os.environ.get(QUIET_HEARTBEAT_SECONDS_ENV, "60"))
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                events = selector.select(timeout=quiet_seconds)
                if not events:
                    if proc.poll() is not None:
                        break
                    heartbeat = (
                        f"# watch_{kind} still running; "
                        f"no child output for {quiet_seconds:g}s\n"
                    )
                    _emit_immediate(heartbeat, progress_f=progress_f, out=out)
                    continue
                line = proc.stdout.readline()
                if line == "":
                    if proc.poll() is not None:
                        break
                    continue
                raw_f.write(line)
                classification = classifier(line)
                cls = classification.cls
                if cls is LineClass.NOISE:
                    continue
                if cls in (
                    LineClass.URGENT,
                    LineClass.SUMMARY,
                    LineClass.METADATA,
                ):
                    _emit_immediate(line, progress_f=progress_f, out=out)
                    if cls is LineClass.SUMMARY:
                        last_summary = line
                    continue
                # PROGRESS — route through the throttle gate.
                decision = gate.consider(classification)
                if decision.emit:
                    _emit_progress(
                        line,
                        suppressed=decision.suppressed_count,
                        progress_f=progress_f,
                        out=out,
                    )

        rc = proc.wait()
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
            summary_footer = (
                f"# watch_{kind} summary: {last_summary.rstrip()}\n"
            )
            _emit_immediate(summary_footer, progress_f=progress_f, out=out)
        footer_extras = ""
        if gate.total_suppressed > 0:
            footer_extras = (
                f" suppressed_total={gate.total_suppressed}"
                f" suppressed_pending={gate.pending_suppressed}"
            )
        footer = (
            f"# watch_{kind} exit={rc} raw={raw_capture}{footer_extras}\n"
        )
        _emit_immediate(footer, progress_f=progress_f, out=out)
        return rc
    finally:
        raw_f.close()
        progress_f.close()


__all__ = [
    "Classifier",
    "PRINT_STREAMING_PAIR_FLAG",
    "QUIET_HEARTBEAT_SECONDS_ENV",
    "WRAPPER_LAUNCH_ERROR",
    "filter_match",
    "mint_capture_paths",
    "print_streaming_pair",
    "regex_classifier",
    "run_watcher",
]
