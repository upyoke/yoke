"""Run the fleet-delta probe under the shared raw+progress watcher.

A steering session's standing wake had no artifact behind it. The loop
told Claude steerers to watch a "fleet-delta probe" that did not exist,
so each session hand-rolled one: a shell loop piping a raw SQL read
through ``jq`` against a scratch state file, with the steerer's session
id and an item-id range baked into the command. That shape breaks the
bare-adapter rule, cannot survive a handoff, and — having no exit
sentinel — leaves its paired follower running after the command stops.

This wrapper is that missing artifact. It runs
:mod:`yoke_core.domain.fleet_delta_probe` under the same raw + throttled-
progress contract as every other watcher, so the probe's delta lines
reach a follower immediately and the run ends with the sentinel that
lets the follower exit.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_fleet"
KIND = "fleet"
DEFAULT_PROG = "watch_fleet"
PROBE_MODULE = "yoke_core.domain.fleet_delta_probe"

# An alarm names a fleet failure that arrives as silence, and a read
# failure means the probe is blind; both outrank any ordinary change.
FLEET_URGENT_RE = re.compile(
    r"^fleet (?:ALARM|ERROR|FATAL)\b|^(?:[\w.]*Error|[\w.]*Exception):"
    r"|^Traceback \(most recent call last\):"
)
# Every ordinary delta is a discrete event worth waking for, so deltas
# are SUMMARY rather than PROGRESS: the throttle must never coalesce
# two different items moving into one reported line.
FLEET_SUMMARY_RE = re.compile(r"^fleet (?:CLEAR|item|session|inbox)\b")
FLEET_PROGRESS_PATTERN = re.compile(
    "|".join((FLEET_URGENT_RE.pattern, FLEET_SUMMARY_RE.pattern))
)


def classify_fleet_line(line: str) -> Classification:
    """Classify one fleet-delta probe output line."""
    if FLEET_URGENT_RE.search(line):
        return Classification(LineClass.URGENT)
    if FLEET_SUMMARY_RE.search(line):
        return Classification(LineClass.SUMMARY)
    return Classification(LineClass.NOISE)


def _probe_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying fleet-delta probe invocation."""
    return [sys.executable, "-m", PROBE_MODULE, *list(args)]


HELP_EPILOG = """\
Pass bare probe arguments after ``--``; the wrapper supplies
``python3 -m yoke_core.domain.fleet_delta_probe``.

The steerer's session id is resolved from ambient harness identity, so
the same command works unedited after a steering handoff. Each pass
reads `sessions.list`, `charge.schedule`, and the durable message
listing, then prints one line per change — and nothing at all while the
fleet is unchanged.

Signal classes:
  inbound envelopes addressed to this session, still unacknowledged
  item status and ownership changes across the watched projects
  session lifecycle: registered, ended, terminated
  ALARM lines for idle claim holders, items unowned past the threshold,
  and starved envelopes (recipients whose session ended are excluded)

examples:
  yoke watch fleet -- --project yoke
  yoke watch fleet -- --project yoke --project platform --interval 30
  yoke watch fleet --print-streaming-pair -- --project yoke

Two invocation shapes, chosen by whether the calling harness has an
idle-wake primitive — a manifest fact, not one this help restates:

  with an idle-wake primitive: arm the `--print-streaming-pair` output
  once. The background line runs the wrapper; the `yoke watch tail`
  line is the subscription, and it exits on the wrapper's sentinel.

  without one: run the wrapper foreground and read its lines from the
  harness's own streaming, bounding the pass with `--duration` so it
  returns to the caller. A foreground pass sees every line the armed
  shape would, only inside one turn instead of across idle time.

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
        help="Print a ready-to-paste background command + progress-tail pair "
        "and exit. Mints fresh capture paths.",
    )
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
    ns = _parse_args(raw, prog)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True
    passthrough = _strip_separator(ns.passthrough)

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        _watch_runner.print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=passthrough,
            raw_capture=raw_path,
            progress_capture=progress_path,
        )
        return 0

    if ns.raw_capture is None or ns.progress_capture is None:
        minted_raw, minted_progress = _watch_runner.mint_capture_paths(KIND)
        raw_path = ns.raw_capture or minted_raw
        progress_path = ns.progress_capture or minted_progress
    else:
        raw_path = ns.raw_capture
        progress_path = ns.progress_capture

    return _watch_runner.run_watcher(
        argv=_probe_argv(passthrough),
        classifier=classify_fleet_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
    )


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
