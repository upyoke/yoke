"""Run the fleet migration preflight under the shared watcher.

The preflight copies and converges every live tenant database before a
release carrying migration history. It can take minutes, so direct execution
leaves callers choosing between buffered output and a hand-authored follower
that cannot observe the watcher exit sentinel.

Use ``yoke watch preflight -- <preflight args>``. The wrapper preserves the
preflight's exit code, forces immediate Python output through the shared
runner, and emits database verdicts, the fleet summary, the receipt, and
failure signatures to its progress capture.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_preflight"
KIND = "preflight"
DEFAULT_PROG = "watch_preflight"
PREFLIGHT_MODULE = "runtime.api.tools.preflight_fleet_migrations"

PREFLIGHT_URGENT_RE = re.compile(
    r"(^FAIL\b|could not (?:copy|read)\b|receipt was not recorded\b"
    r"|release gate will still refuse\b|^Traceback \(most recent call last\):"
    r"|^(?:[\w.]*Error|[\w.]*Exception):|^fatal:)",
    re.IGNORECASE,
)
PREFLIGHT_SUMMARY_RE = re.compile(
    r"(^PASS\b|^\d+ passed,\s+\d+ failed\b|^receipt recorded\b)",
    re.IGNORECASE,
)
PREFLIGHT_PROGRESS_RE = re.compile(
    r"(^engine artifact:|^environment:|^rehearsal cluster:"
    r"|^\s*(?:copy(?:ing)?|converg(?:e|ing))\b)",
    re.IGNORECASE,
)
PREFLIGHT_PROGRESS_PATTERN = re.compile(
    "|".join(
        (
            PREFLIGHT_URGENT_RE.pattern,
            PREFLIGHT_SUMMARY_RE.pattern,
            PREFLIGHT_PROGRESS_RE.pattern,
        )
    ),
    re.IGNORECASE,
)


def classify_preflight_line(line: str) -> Classification:
    """Classify one fleet-preflight output line."""
    if PREFLIGHT_URGENT_RE.search(line):
        return Classification(LineClass.URGENT)
    if PREFLIGHT_SUMMARY_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if PREFLIGHT_PROGRESS_RE.search(line):
        return Classification(LineClass.PROGRESS)
    return Classification(LineClass.NOISE)


def _preflight_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying project preflight invocation."""
    return [sys.executable, "-m", PREFLIGHT_MODULE, *list(args)]


HELP_EPILOG = """\
examples:
  yoke watch preflight -- prod-db-admin \\
      --engine-wheel /path/to/yoke_core-release.whl --record-receipt \\
      --product-sha SHA --receipt-env prod

  yoke watch preflight --print-streaming-pair -- \\
      prod-db-admin --engine-wheel /path/to/yoke_core-release.whl \\
      --record-receipt --product-sha SHA --receipt-env prod

Pass bare preflight arguments after ``--``. The wrapper supplies
``python3 -m runtime.api.tools.preflight_fleet_migrations``.

When a release-surface capability contract blocks a receipt: read the
stored document with ``yoke projects capability-settings get``, then
either converge it with ``capability-settings set --base <as-read>`` or
remove it with ``capability-settings remove --base <as-read>`` when it
carries no policy. Never guess an enum value or hand-edit SQL.
"""


def _parse_args(
    argv: Sequence[str],
    prog: str = DEFAULT_PROG,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Run the fleet migration preflight under the shared raw+progress watcher."
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
        help="Bare preflight arguments, separated from wrapper flags by --.",
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
        argv=_preflight_argv(passthrough),
        classifier=classify_preflight_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
    )


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
