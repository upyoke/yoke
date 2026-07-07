"""Command-shaped watcher for Yoke's merge engines.

Owns the merge line classifier so callers do not author a Monitor
filter per invocation. The classifier covers the step headers, status
transitions, errors, hard stops, and merge test substream lines emitted
by ``yoke_core.engines.done_transition`` and
``yoke_core.engines.merge_worktree``.

Class assignments:

- Errors / warnings / hard stops / fatals, including failures inside
  merge test substreams → ``URGENT``.
- Section banners (``=== ... ===``), result emissions
  (``RESULT_FILE=``, ``YOKE_REPO_ROOT=``), and high-level merge state
  transitions (``Merging branch:``, ``Worktree:``,
  ``Branch already merged``, ``Resuming from step``, ``Pre-flight:``,
  ``Merge already completed``) → ``SUMMARY``.
- Step headers (``Step N``) and merge-time test substream lines
  (``[tests] ...``, ``[phase:tests] ...``, generic ``[phase:...] ...``)
  → ``PROGRESS`` (time-window throttled).

Every other line is ``NOISE`` (raw capture only).

Usage::

    python3 -m yoke_core.tools.watch_merge done-transition YOK-N
    python3 -m yoke_core.tools.watch_merge merge-worktree \\
        --branch YOK-N --target main

    # Print the ready-to-paste streaming pair:
    python3 -m yoke_core.tools.watch_merge --print-streaming-pair -- \\
        done-transition YOK-N

The wrapper preserves the underlying engine's exit code.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_merge"
KIND = "merge"

# Maps wrapper sub-command names to the underlying engine module.
SUBCOMMAND_MODULES: dict[str, str] = {
    "done-transition": "yoke_core.engines.done_transition",
    "merge-worktree": "yoke_core.engines.merge_worktree",
}

# Per-class regexes. Each is line-oriented and used by
# :func:`classify_merge_line` directly. The public union pattern below
# is composed from these so the existing ``filter_match`` callers keep
# working.
MERGE_URGENT_PREFIXES: tuple[str, ...] = (
    "Error:",
    "ERROR:",
    "Warning:",
    "HARD STOP:",
    "Merge halted:",
    "Merge lock error:",
    "fatal:",
)
MERGE_SUMMARY_PREFIXES: tuple[str, ...] = (
    "===",
    "Merging branch:",
    "Worktree:",
    "Branch already merged",
    "Resuming from step",
    "Pre-flight:",
    "Merge already completed",
    "RESULT_FILE=",
    "YOKE_REPO_ROOT=",
)
MERGE_STEP_RE = re.compile(r"^Step \d")
# Merge-time test substream and phase-prefixed lines emitted by
# yoke_core.engines.merge_worktree_tests.
MERGE_TEST_SUBSTREAM_RE = re.compile(r"^\[(tests|phase:[^\]]+)\]")
MERGE_TEST_PERCENT_RE = re.compile(r"\[\s*(\d+)%\]")
MERGE_TEST_URGENT_PREFIXES: tuple[str, ...] = (
    "FAILED ",
    "ERROR ",
    *MERGE_URGENT_PREFIXES,
)
MERGE_TEST_SUMMARY_RE = re.compile(
    r"^(?:=+ .*(passed|failed|error)|collected \d+)"
)


def _test_substream_payload(line: str) -> str | None:
    """Return payload after a merge test-stream prefix, when present."""
    match = MERGE_TEST_SUBSTREAM_RE.match(line)
    if match is None:
        return None
    return line[match.end():].lstrip()


def classify_merge_line(line: str) -> Classification:
    """Classify a single output line from a Yoke merge engine."""
    for prefix in MERGE_URGENT_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.URGENT)
    for prefix in MERGE_SUMMARY_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.SUMMARY)
    if MERGE_STEP_RE.search(line):
        return Classification(LineClass.PROGRESS)
    payload = _test_substream_payload(line)
    if payload is not None:
        if any(payload.startswith(prefix) for prefix in MERGE_TEST_URGENT_PREFIXES):
            return Classification(LineClass.URGENT)
        if MERGE_TEST_SUMMARY_RE.search(payload):
            return Classification(LineClass.SUMMARY)
        percent = MERGE_TEST_PERCENT_RE.search(payload)
        if percent:
            return Classification(
                LineClass.PROGRESS, progress_value=float(percent.group(1))
            )
        return Classification(LineClass.PROGRESS)
    return Classification(LineClass.NOISE)


def _build_merge_progress_pattern() -> re.Pattern[str]:
    """Compose the public union regex from the class-specific regexes.

    All prefix-based alternatives are anchored to line start with ``^``
    so :func:`yoke_core.tools._watch_runner.filter_match` keeps the
    "is this a signal line?" semantics — a stray ``Error:`` mid-line
    (for example, inside a quoted string) must NOT count as a banner.
    """
    parts: list[str] = []
    parts.extend("^" + re.escape(p) for p in MERGE_URGENT_PREFIXES)
    parts.extend("^" + re.escape(p) for p in MERGE_SUMMARY_PREFIXES)
    parts.append(MERGE_STEP_RE.pattern)
    parts.append(MERGE_TEST_SUBSTREAM_RE.pattern)
    return re.compile("|".join(parts))


# Public union pattern, retained so legacy filter-coverage tests keep
# their single source of truth and so any operator-facing tooling that
# greps for "is this a merge signal?" still works.
MERGE_PROGRESS_PATTERN = _build_merge_progress_pattern()


def _resolve_subcommand(args: Sequence[str]) -> tuple[str, list[str]]:
    """Resolve the merge sub-command and return ``(module, passthrough)``.

    Raises :class:`SystemExit` when the sub-command is missing or unknown.
    """
    if not args:
        sys.stderr.write(
            "watch_merge: missing sub-command (one of "
            f"{', '.join(sorted(SUBCOMMAND_MODULES))})\n"
        )
        raise SystemExit(2)
    sub = args[0]
    module = SUBCOMMAND_MODULES.get(sub)
    if module is None:
        sys.stderr.write(
            f"watch_merge: unknown sub-command {sub!r}; expected one of "
            f"{', '.join(sorted(SUBCOMMAND_MODULES))}\n"
        )
        raise SystemExit(2)
    return module, list(args[1:])


def _engine_argv(module: str, args: Sequence[str]) -> list[str]:
    """Build the underlying engine invocation argv."""
    return [sys.executable, "-m", module, *list(args)]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watch_merge",
        description=(
            "Run a Yoke merge engine under a shared raw+progress watcher."
        ),
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
        help="Explicit raw capture file path. Defaults to a helper-resolved "
        "path under the project scratch root.",
    )
    parser.add_argument(
        "--progress-capture",
        type=Path,
        default=None,
        help="Explicit progress capture file path. Defaults to a helper-"
        "resolved path under the project scratch root.",
    )
    parser.add_argument(
        "passthrough",
        nargs=argparse.REMAINDER,
        help="Sub-command name followed by its arguments. Use ``--`` to "
        "separate wrapper flags from sub-command args when ambiguous.",
    )
    return parser.parse_args(list(argv))


def _strip_separator(passthrough: list[str]) -> list[str]:
    """Strip stray ``--`` separators argparse left in REMAINDER.

    Drops both:

    1. A leading ``--`` (between wrapper flags and the subcommand).
    2. A ``--`` between the subcommand name and its args. Operators
       commonly insert this separator for clarity, and the
       streaming-pair output previously echoed it verbatim into
       the printed Bash invocation. Without this strip, ``merge-worktree``
       received ``--`` as its first positional and failed with
       ``Error: branch '--' does not exist as a local ref``.
    """
    args = list(passthrough)
    if args and args[0] == "--":
        args = args[1:]
    if len(args) >= 2 and args[1] == "--":
        args = [args[0]] + args[2:]
    return args


def _extract_print_streaming_pair(argv: list[str]) -> tuple[list[str], bool]:
    """Pull ``--print-streaming-pair`` out of any position in ``argv``.

    ``passthrough`` uses ``nargs=argparse.REMAINDER``, which means the
    flag is forwarded into the sub-command when it appears after the
    subcommand name (`merge-worktree --print-streaming-pair ...`) — the
    underlying merge engine then interprets it as a positional branch.
    Pre-extracting the flag makes every position equivalent.
    """
    filtered: list[str] = []
    found = False
    for arg in argv:
        if arg == _watch_runner.PRINT_STREAMING_PAIR_FLAG:
            found = True
            continue
        filtered.append(arg)
    return filtered, found


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw, print_streaming_pair_flag = _extract_print_streaming_pair(raw)
    ns = _parse_args(raw)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True
    sub_args = _strip_separator(list(ns.passthrough))

    if ns.print_streaming_pair:
        # We embed the sub-command verbatim in the printed Bash invocation
        # so the operator pastes it as-is. Resolve enough to validate.
        if sub_args:
            module = SUBCOMMAND_MODULES.get(sub_args[0])
            if module is None:
                sys.stderr.write(
                    f"watch_merge: unknown sub-command "
                    f"{sub_args[0]!r}; expected one of "
                    f"{', '.join(sorted(SUBCOMMAND_MODULES))}\n"
                )
                return 2
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        _watch_runner.print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=sub_args,
            raw_capture=raw_path,
            progress_capture=progress_path,
        )
        return 0

    module, passthrough = _resolve_subcommand(sub_args)

    if ns.raw_capture is None or ns.progress_capture is None:
        minted_raw, minted_progress = _watch_runner.mint_capture_paths(KIND)
        raw_path = ns.raw_capture or minted_raw
        progress_path = ns.progress_capture or minted_progress
    else:
        raw_path = ns.raw_capture
        progress_path = ns.progress_capture

    return _watch_runner.run_watcher(
        argv=_engine_argv(module, passthrough),
        classifier=classify_merge_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
