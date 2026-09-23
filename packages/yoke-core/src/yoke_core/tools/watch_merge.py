"""Command-shaped watcher for Yoke's merge engines.

Owns the merge line classifier so callers do not author a Monitor
filter per invocation. It covers what
``yoke_core.engines.done_transition`` and
``yoke_core.engines.merge_worktree`` emit; the class constants below
carry the per-shape assignments, and every other line is ``NOISE``
(raw capture only). Only terminal errors and the final result reach the
user-facing stream. Routine progress and watcher metadata stay out of the
stream; the raw capture retains the complete child output.

Usage::

    yoke watch merge done-transition YOK-N
    yoke watch merge merge-worktree \\
        --branch YOK-N --target main

    # Print the ready-to-paste streaming pair:
    yoke watch merge --print-streaming-pair -- \\
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
from yoke_core.tools._watch_terminal_outcome import (
    OUTCOME_ONLY_WATCH_KINDS,
    PYTHON_EXCEPTION_PATTERN,
    is_python_exception_line,
)
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_merge"
KIND = "merge"
# argparse prog for a direct module invocation; the CLI adapter
# passes the ``yoke watch merge`` form so help reads back the
# command as typed.
DEFAULT_PROG = "watch_merge"

# Maps wrapper sub-command names to the module that owns the run. Each
# must be the same entrypoint the plain command uses, not the engine that
# entrypoint eventually calls: `yoke merge item` reaches the standalone
# merge through a runtime that first binds this machine's GitHub user
# authority, and a wrapper that skipped straight to the engine merged
# without it — visibly, as a credential refusal on any machine whose App
# authority lives server-side.
SUBCOMMAND_MODULES: dict[str, str] = {
    "done-transition": "yoke_core.engines.done_transition",
    "merge-item": "yoke_cli.commands.merge_item_local_runtime",
    "merge-worktree": "yoke_core.engines.merge_worktree",
}

# Per-class regexes drive classification; the public pattern below is their union.
MERGE_URGENT_PREFIXES: tuple[str, ...] = (
    "Error:",
    "ERROR:",
    "Warning:",
    "HARD STOP:",
    "Merge halted:",
    "Merge lock error:",
    "fatal:",
)
_MERGE_URGENT_WARNING_RE = re.compile(
    r"^Warning:(?!.*(?i:\b(?:transient|temporar(?:y|ily)|"
    r"retry(?:ing)?|try again)\b))"
)
# Terminal results and verdicts that end the merge before it starts.
MERGE_SUMMARY_PREFIXES: tuple[str, ...] = (
    "Branch already merged",
    "Merge already completed",
    "RESULT_FILE=",
    "YOKE_REPO_ROOT=",
)
# Routine motion is retained in raw capture, not the user-facing stream.
MERGE_PROGRESS_PREFIXES: tuple[str, ...] = (
    "===",
    "Merging branch:",
    "Worktree:",
    "Resuming from step",
    "Pre-flight:",
)
MERGE_STEP_RE = re.compile(r"^Step \d")
# Queue poll observations remain classified as progress for diagnostics.
MERGE_QUEUE_POLL_RE = re.compile(r"^Queue landing: ")
# Merge-time test substream and phase-prefixed lines.
MERGE_TEST_SUBSTREAM_RE = re.compile(r"^\[(tests|phase:[^\]]+)\]")
MERGE_TEST_PERCENT_RE = re.compile(r"\[\s*(\d+)%\]")
MERGE_TEST_URGENT_PREFIXES: tuple[str, ...] = (
    "FAILED ",
    "ERROR ",
    *MERGE_URGENT_PREFIXES,
)
MERGE_TEST_SUMMARY_RE = re.compile(r"^(?:=+ .*(passed|failed|error)|collected \d+)")


def _test_substream_payload(line: str) -> str | None:
    """Return payload after a merge test-stream prefix, when present."""
    match = MERGE_TEST_SUBSTREAM_RE.match(line)
    if match is None:
        return None
    return line[match.end() :].lstrip()


def classify_merge_line(line: str) -> Classification:
    """Classify a single output line from a Yoke merge engine."""
    if is_python_exception_line(line):
        return Classification(LineClass.URGENT)
    if line.startswith("Warning:"):
        warning_class = (
            LineClass.URGENT
            if _MERGE_URGENT_WARNING_RE.match(line)
            else LineClass.NOISE
        )
        return Classification(warning_class)
    for prefix in MERGE_URGENT_PREFIXES:
        if prefix == "Warning:":
            continue
        if line.startswith(prefix):
            return Classification(LineClass.URGENT)
    for prefix in MERGE_SUMMARY_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.SUMMARY)
    for prefix in MERGE_PROGRESS_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.PROGRESS)
    if MERGE_STEP_RE.search(line) or MERGE_QUEUE_POLL_RE.search(line):
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
    """Build the public union pattern from classifier signal lines."""
    parts: list[str] = []
    parts.extend(
        "^" + re.escape(prefix)
        for prefix in MERGE_URGENT_PREFIXES
        if prefix != "Warning:"
    )
    parts.append(_MERGE_URGENT_WARNING_RE.pattern)
    parts.append(PYTHON_EXCEPTION_PATTERN.pattern)
    parts.extend("^" + re.escape(p) for p in MERGE_SUMMARY_PREFIXES)
    parts.extend("^" + re.escape(p) for p in MERGE_PROGRESS_PREFIXES)
    parts.append(MERGE_STEP_RE.pattern)
    parts.append(MERGE_QUEUE_POLL_RE.pattern)
    parts.append(MERGE_TEST_SUBSTREAM_RE.pattern)
    return re.compile("|".join(parts))


# Public union retained for filter-coverage tests and signal tooling.
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


def _parse_args(
    argv: Sequence[str],
    prog: str = DEFAULT_PROG,
) -> argparse.Namespace:
    subcommands = ", ".join(sorted(SUBCOMMAND_MODULES))
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Run a Yoke merge engine with outcome-only watcher output. "
            "Routine progress is suppressed; the raw capture keeps full output. "
            f"Sub-commands: {subcommands}. "
            "Pass-through flags include --local-verification (force local "
            "post-rebase suite even when the project declares CI; CI routing "
            "frees the local admission slot, not wall-clock latency). "
            "merge-item enqueues and exits by default; re-enter after landing."
        ),
        epilog=(
            f"Examples:\n"
            f"  {prog} merge-item -- PREFIX-N --result TEXT --verification TEXT\n"
            f"  {prog} merge-item -- PREFIX-N --wait --result TEXT --verification TEXT\n"
            f"  {prog} merge-worktree -- PREFIX-N\n"
            f"  {prog} done-transition -- PREFIX-N\n"
            "--wait holds the landing inline. Invoke it with\n"
            "--print-streaming-pair to print the safe shape without\n"
            "merging anything: a native idle-wake primitive gets the\n"
            "background pair; headless relay-launched workers, and\n"
            "harnesses with no or unverified idle wake, get the foreground\n"
            "invocation to hold open. Run the printed command to merge."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        _watch_runner.PRINT_STREAMING_PAIR_FLAG,
        dest="print_streaming_pair",
        action="store_true",
        help=_watch_runner.STREAMING_WAIT_HELP,
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
        metavar="{" + subcommands.replace(", ", ",") + "} ...",
        help=f"One of {subcommands}, followed by its arguments. Use ``--`` "
        "to separate wrapper flags from sub-command args when ambiguous.",
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


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw, print_streaming_pair_flag = _extract_print_streaming_pair(raw)
    ns = _parse_args(raw, prog)
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
        return _watch_runner.print_wait_mode_invocation(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=sub_args,
            raw_capture=raw_path,
            progress_capture=progress_path,
            outcome_only=KIND in OUTCOME_ONLY_WATCH_KINDS,
        )

    module, passthrough = _resolve_subcommand(sub_args)

    raw_path, progress_path = _watch_runner.bind_capture_paths(ns, KIND)

    return _watch_runner.run_watcher(
        argv=_engine_argv(module, passthrough),
        classifier=classify_merge_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
        outcome_only=KIND in OUTCOME_ONLY_WATCH_KINDS,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
