"""Run the fleet-delta probe under the shared raw+progress watcher.

A steering session's standing wake had no artifact behind it. The loop
told Claude steerers to watch a "fleet-delta probe" that did not exist,
so each session hand-rolled one: a shell loop piping a raw SQL read
through ``jq`` against a scratch state file, with the steerer's session
id and an item-id range baked into the command. That shape breaks the
bare-adapter rule, cannot survive a handoff, and — having no exit
sentinel — leaves its paired follower running after the command stops.

This wrapper runs :mod:`yoke_core.domain.fleet_delta_probe` under the shared
raw + progress contract. Its central tier table sends actionable deltas to
the follower immediately, keeps routine churn raw until the next report
wake, and always ends with the follower's sentinel.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.domain import fleet_delta_probe
from yoke_core.domain.steering_fleet_report_render import REPORT_BEGIN
from yoke_core.tools import _watch_digest, _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_fleet"
KIND = "fleet"
DEFAULT_PROG = "watch_fleet"
PROBE_MODULE = "yoke_core.domain.fleet_delta_probe"

PROCESS_FAILURE_RE = re.compile(
    r"^(?:[\w.]*Error|[\w.]*Exception):"
    r"|^Traceback \(most recent call last\):"
)


def classify_fleet_line(line: str) -> Classification:
    """Classify one fleet-delta probe output line."""
    if PROCESS_FAILURE_RE.search(line) or line.rstrip() == REPORT_BEGIN:
        return Classification(LineClass.URGENT)
    if fleet_delta_probe.delta_wake_tier(line) == fleet_delta_probe.WAKE_NOW:
        return Classification(LineClass.URGENT)
    return Classification(LineClass.NOISE)


def _probe_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying fleet-delta probe invocation."""
    return [sys.executable, "-m", PROBE_MODULE, *list(args)]


HELP_EPILOG = """\
Pass bare probe arguments after ``--``; the wrapper supplies
``python3 -m yoke_core.domain.fleet_delta_probe``:

  --project P    Project to watch. Repeatable. Defaults to the
                 checkout's mapped project.
  --interval N   Seconds between passes (default 60).
  --duration N   Seconds to poll before exiting cleanly (default 3600;
                 0 runs until interrupted). A bounded run always writes
                 the exit sentinel, so an armed follower always ends.

The negative-space thresholds are the steering loop's and are not
flags: a claim holder idle past 20 minutes, an in-flight item unowned
continuously past 15, an envelope undelivered past 10.

The steerer's session id comes from ambient harness identity, so the same
command survives handoff. Every delta remains in the raw capture. The wake
stream emits worker messages, alarms, abnormal session ends, blocked item
transitions, read failures, and one marker for a changed rate-limited report.
Healthy item transitions, claim churn, registrations, clean ends, and alarm
clears stay silent at delta time and surface through the next report. Pull its
full body with `yoke steering report get`.

examples:
  yoke watch fleet -- --project yoke
  yoke watch fleet -- --project yoke --project platform --interval 30
  yoke watch fleet --print-streaming-pair -- --project yoke

`--print-streaming-pair` chooses between two invocation shapes from the
calling session's manifest wake fact:

  with a native idle-wake primitive: it reports `wait_mode=background-wake`
  and prints a background wrapper plus `yoke watch tail` subscription. The
  subscription exits on the wrapper's sentinel and may wake the caller.

  as a headless relay-launched worker, or with no or unverified idle
  wake: it reports `wait_mode=in-turn` and immediately runs the wrapper
  foreground,
  bounding the pass with `--duration` so it returns to the caller. A
  foreground pass sees every line the armed shape would, only inside one
  turn instead of across idle time.

The wrapper is a local read. It delivers nothing to anyone, and no
report depends on it running.
"""


def _parse_args(
    argv: Sequence[str],
    prog: str = DEFAULT_PROG,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Run the fleet-delta probe under the shared raw+progress watcher."
        ),
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        _watch_runner.PRINT_STREAMING_PAIR_FLAG,
        dest="print_streaming_pair",
        action="store_true",
        help=_watch_runner.STREAMING_WAIT_HELP,
    )
    _watch_digest.attach_flush_seconds(parser)
    parser.add_argument(
        "--raw-capture",
        type=Path,
        default=None,
        help="Explicit raw capture path. Defaults under project scratch.",
    )
    parser.add_argument(
        "--progress-capture",
        type=Path,
        default=None,
        help="Explicit progress capture path. Defaults under project scratch.",
    )
    parser.add_argument(
        "passthrough",
        nargs=argparse.REMAINDER,
        help="Bare probe arguments, separated from wrapper flags by --.",
    )
    return parser.parse_args(list(argv))


def _extract_print_streaming_pair(argv: list[str]) -> tuple[list[str], bool]:
    """Make ``--print-streaming-pair`` position-independent."""
    filtered: list[str] = []
    found = False
    for arg in argv:
        if arg == _watch_runner.PRINT_STREAMING_PAIR_FLAG:
            found = True
            continue
        filtered.append(arg)
    return filtered, found


def _strip_separator(passthrough: Sequence[str]) -> list[str]:
    args = list(passthrough)
    if args and args[0] == "--":
        args = args[1:]
    return args


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw, print_streaming_pair_flag = _extract_print_streaming_pair(raw)
    raw, flush_seconds = _watch_digest.extract_flush_seconds(raw)
    ns = _parse_args(raw, prog)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True
    passthrough = _strip_separator(ns.passthrough)

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        return _watch_runner.run_or_print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=passthrough,
            raw_capture=raw_path,
            progress_capture=progress_path,
            wrapper_options=_watch_digest.streaming_pair_options(flush_seconds),
        )

    raw_path, progress_path = _watch_runner.bind_capture_paths(ns, KIND)

    return _watch_runner.run_watcher(
        argv=_probe_argv(passthrough),
        classifier=classify_fleet_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
        flush_seconds=_watch_digest.resolve_flush_seconds(ns, flush_seconds),
    )


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
