"""Command-shaped watcher for Yoke's lifecycle-status writers.

Owns the lifecycle-status line classifier so callers do not author a
Monitor filter per invocation. Lifecycle status writes route through
the function dispatcher (board rebuild + GitHub sync; 30-60s observed
in live sessions) and the sibling ``repair_status`` engine. The shared
classifier covers section banners, step headers, gate denials, sync
progress, retry guards, and the final JSON envelope.

Class assignments:

- ``Error:`` / ``ERROR:`` / ``Warning:`` / ``Status update failed`` /
  ``BLOCKED:`` / ``GATE_…`` denial lines → ``URGENT``.
- ``=== Step …`` / ``=== Done transition:`` section banners and
  ``Status verified: …`` / ``Sub-task cascade complete:`` /
  ``Batch GitHub sync complete.`` summary lines, plus the final JSON
  envelope on stdout → ``SUMMARY``.
- ``--- <section> ---`` block banners, indented progress lines
  (``  merged_at``, ``  Promoted:``, ``  Cascaded:``, ``  GitHub:``),
  and the retry guard line (``Status is still …``) → ``PROGRESS``
  (time-window throttled).

Every other line is ``NOISE`` (raw capture only).

Usage::

    # Drive `db_router items update YOK-N status <value>`:
    python3 -m yoke_core.tools.watch_lifecycle items-update-status \\
        -- YOK-N status implementing

    # Drive `yoke_core.engines.repair_status`:
    python3 -m yoke_core.tools.watch_lifecycle repair-status -- YOK-N

    # Print the ready-to-paste streaming pair:
    python3 -m yoke_core.tools.watch_lifecycle --print-streaming-pair \\
        items-update-status -- YOK-N status implementing

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

WRAPPER_MODULE = "yoke_core.tools.watch_lifecycle"
KIND = "lifecycle"

# Maps wrapper sub-command names to ``(module, prefix_args)``. The
# wrapper supplies the underlying ``python3 -m <module>`` plus the
# fixed prefix args; callers pass any remaining bare args after ``--``.
# ``items-update-status`` covers the canonical
# ``db_router items update <id> status <value>`` shape; ``repair-status``
# covers the ``repair_status`` engine.
SUBCOMMAND_MODULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "items-update-status": ("yoke_core.cli.db_router", ("items", "update")),
    "repair-status": ("yoke_core.engines.repair_status", ()),
}

# Per-class regexes. Each is line-oriented; callers feed one line at a
# time.
LIFECYCLE_URGENT_RE = re.compile(
    r"^(Error:|ERROR:|Warning:|BLOCKED:|Status update failed|"
    r"Usage:|HARD STOP:|GATE_[A-Z_]+)",
)
LIFECYCLE_SUMMARY_RE = re.compile(
    r"^(===|Status verified:|Sub-task cascade complete:|"
    r"Batch GitHub sync complete\.|YOKE_REPO_ROOT=|RESULT_FILE=)",
)
# Function-call dispatcher emits a JSON envelope on stdout when the
# write succeeds. We treat any line starting with ``{"success"`` or
# ``{"item_id"`` as a verdict-bearing summary.
LIFECYCLE_SUMMARY_JSON_RE = re.compile(r'^\{"(success|item_id|outcome)"')
LIFECYCLE_PROGRESS_RE = re.compile(
    r"^(--- |  merged_at|  Promoted:|  Cascaded:|  GitHub:|"
    r"Status is still|Installing|Rebuilding board|Syncing GitHub)",
)


# Public union pattern: kept for callers/tests that want a single
# "is this a signal line?" check. Composed from the per-class regexes
# above so there is exactly one source of truth for each shape.
LIFECYCLE_PROGRESS_PATTERN = re.compile(
    r"|".join(
        (
            LIFECYCLE_URGENT_RE.pattern,
            LIFECYCLE_SUMMARY_RE.pattern,
            LIFECYCLE_SUMMARY_JSON_RE.pattern,
            LIFECYCLE_PROGRESS_RE.pattern,
        )
    )
)


def classify_lifecycle_line(line: str) -> Classification:
    """Classify a single lifecycle-status writer output line.

    Order matters: failure lines that *also* contain other tokens must
    still classify as ``URGENT`` so they emit immediately. We check
    URGENT and SUMMARY before PROGRESS for that reason.
    """
    if LIFECYCLE_URGENT_RE.search(line):
        return Classification(LineClass.URGENT)
    if LIFECYCLE_SUMMARY_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if LIFECYCLE_SUMMARY_JSON_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if LIFECYCLE_PROGRESS_RE.search(line):
        return Classification(LineClass.PROGRESS)
    return Classification(LineClass.NOISE)


def _resolve_subcommand(args: Sequence[str]) -> tuple[str, tuple[str, ...], list[str]]:
    """Resolve the lifecycle sub-command and return
    ``(module, prefix_args, passthrough)``.

    Raises :class:`SystemExit` when the sub-command is missing or unknown.
    """
    if not args:
        sys.stderr.write(
            "watch_lifecycle: missing sub-command (one of "
            f"{', '.join(sorted(SUBCOMMAND_MODULES))})\n"
        )
        raise SystemExit(2)
    sub = args[0]
    spec = SUBCOMMAND_MODULES.get(sub)
    if spec is None:
        sys.stderr.write(
            f"watch_lifecycle: unknown sub-command {sub!r}; expected "
            f"one of {', '.join(sorted(SUBCOMMAND_MODULES))}\n"
        )
        raise SystemExit(2)
    module, prefix = spec
    return module, prefix, list(args[1:])


def _engine_argv(module: str, prefix: Sequence[str], args: Sequence[str]) -> list[str]:
    """Build the underlying engine invocation argv."""
    return [sys.executable, "-m", module, *list(prefix), *list(args)]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watch_lifecycle",
        description=(
            "Run a Yoke lifecycle-status writer under the shared "
            "raw+progress watcher wrapper."
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
       the printed Bash invocation. Without this strip, the
       subcommand received ``--`` as its first positional and
       failed before doing useful work.
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
    subcommand name. Pre-extracting makes every position equivalent.
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
        # We embed the sub-command verbatim in the printed Bash
        # invocation so the operator pastes it as-is. Resolve enough
        # to validate.
        if sub_args:
            spec = SUBCOMMAND_MODULES.get(sub_args[0])
            if spec is None:
                sys.stderr.write(
                    f"watch_lifecycle: unknown sub-command "
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

    module, prefix, passthrough = _resolve_subcommand(sub_args)

    if ns.raw_capture is None or ns.progress_capture is None:
        minted_raw, minted_progress = _watch_runner.mint_capture_paths(KIND)
        raw_path = ns.raw_capture or minted_raw
        progress_path = ns.progress_capture or minted_progress
    else:
        raw_path = ns.raw_capture
        progress_path = ns.progress_capture

    return _watch_runner.run_watcher(
        argv=_engine_argv(module, prefix, passthrough),
        classifier=classify_lifecycle_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
