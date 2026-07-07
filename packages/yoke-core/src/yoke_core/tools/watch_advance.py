"""Command-shaped watcher for ``yoke_core.engines.advance_implementation_entry`` runs.

Owns the advance-orchestrator line classifier so callers do not author
a Monitor filter per invocation. Worktree creation + preflight gate
evaluation + claim activation routinely cross the ~60s threshold
(60-120s observed in live sessions; the worktree phase alone runs
``npm ci`` / ``pip install`` / ``playwright install`` inside the new
checkout). Without a wrapper, every agent invocation re-derives the
progress regex and the redirection-order trap blinds the operator.

The classifier maps:

- ``ERROR:`` / ``BLOCKED:`` / ``Warning:`` / ``Status update failed``
  hard-stop lines → ``URGENT`` (immediate emit).
- ``Playwright cache:``, ``Installing deps``, ``Detected nested ...``,
  ``No dependency files detected``, ``Validation surface provisioned:``
  stage progress lines → ``PROGRESS`` (time-window throttled).
- The final orchestrator summary line — a single JSON envelope starting
  with ``{"item_id":`` — → ``SUMMARY``.

Every other line is ``NOISE`` (raw capture only).

Usage::

    # Direct execution (Codex / shell): streams filtered progress to
    # stdout while preserving full output in the raw capture. Pass any
    # advance flags after ``--``; the wrapper supplies the
    # ``python3 -m yoke_core.engines.advance_implementation_entry``
    # prefix itself.
    python3 -m yoke_core.tools.watch_advance -- --item YOK-N

    # Print the ready-to-paste streaming pair for Claude Code:
    python3 -m yoke_core.tools.watch_advance --print-streaming-pair -- --item YOK-N

    # Explicit capture paths (used by --print-streaming-pair output):
    python3 -m yoke_core.tools.watch_advance \\
        --raw-capture /tmp/raw.log --progress-capture /tmp/prog.log \\
        -- --item YOK-N

The wrapper preserves the orchestrator's exit code so callers can still
branch on success/failure.

Do NOT pass a full advance command-shape after ``--``. The wrapper
rejects ``-- python3 -m yoke_core.engines.advance_implementation_entry …``
(and the ``python``, ``sys.executable``, and ``pythonX.Y`` variants)
before invoking the underlying runner.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_advance"
KIND = "advance"
UNDERLYING_MODULE = "yoke_core.engines.advance_implementation_entry"

# Per-class regexes. Each is line-oriented; callers feed one line at a
# time. Keeping them as separate constants lets tests exercise each
# class independently without re-parsing the union pattern.
ADVANCE_URGENT_RE = re.compile(
    r"^(ERROR:|BLOCKED:|Warning:|Status update failed|HARD STOP:)",
)
ADVANCE_PROGRESS_RE = re.compile(
    r"^(Playwright cache:|Installing deps|Detected nested|"
    r"No dependency files detected|Validation surface provisioned:|"
    r"Status is still)",
)
# Final orchestrator JSON summary: stdout emits one line starting with
# ``{"item_id":``. That envelope carries the run's verdict.
ADVANCE_SUMMARY_RE = re.compile(r'^\{"item_id":')


# Public union pattern: kept for callers/tests that want a single
# "is this a signal line?" check. Composed from the per-class regexes
# above so there is exactly one source of truth for each shape.
ADVANCE_PROGRESS_PATTERN = re.compile(
    r"|".join(
        (
            ADVANCE_URGENT_RE.pattern,
            ADVANCE_PROGRESS_RE.pattern,
            ADVANCE_SUMMARY_RE.pattern,
        )
    )
)


def classify_advance_line(line: str) -> Classification:
    """Classify a single advance-orchestrator output line.

    Order matters: failure lines that *also* contain other tokens must
    still classify as ``URGENT`` so they emit immediately. We check
    URGENT and SUMMARY before PROGRESS for that reason.
    """
    if ADVANCE_URGENT_RE.search(line):
        return Classification(LineClass.URGENT)
    if ADVANCE_SUMMARY_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if ADVANCE_PROGRESS_RE.search(line):
        return Classification(LineClass.PROGRESS)
    return Classification(LineClass.NOISE)


NESTED_ADVANCE_REJECTION_MESSAGE = (
    "watch_advance expects bare advance args after --; "
    f"do not include python3 -m {UNDERLYING_MODULE}.\n"
    "Example: python3 -m yoke_core.tools.watch_advance -- --item YOK-N"
)

# Match the bare interpreter names operators most commonly retype, plus
# the literal ``sys.executable`` token (sometimes copied from the
# wrapper source). Path forms (``/usr/bin/python3``) reuse this against
# the basename so we accept them without separately enumerating
# prefixes.
_PYTHON_BASENAME_RE = re.compile(r"^python(\d+(\.\d+)?)?$")


def _looks_like_python_executable(token: str) -> bool:
    """Return True when ``token`` names a Python interpreter."""
    if token == "sys.executable":
        return True
    base = token.rsplit("/", 1)[-1]
    return bool(_PYTHON_BASENAME_RE.match(base))


def _is_nested_advance_invocation(args: Sequence[str]) -> bool:
    """Return True if pass-through ``args`` start with
    ``<python> -m yoke_core.engines.advance_implementation_entry``.
    """
    if len(args) < 3:
        return False
    return (
        _looks_like_python_executable(args[0])
        and args[1] == "-m"
        and args[2] == UNDERLYING_MODULE
    )


def _advance_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying advance invocation."""
    return [sys.executable, "-m", UNDERLYING_MODULE, *list(args)]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watch_advance",
        description=(
            "Run advance_implementation_entry under the shared "
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
        help=(
            "Bare advance_implementation_entry arguments. Use ``--`` to "
            "separate wrapper flags from advance flags. Do NOT include "
            f"``python3 -m {UNDERLYING_MODULE}``; the wrapper supplies "
            "that prefix."
        ),
    )
    return parser.parse_args(list(argv))


def _strip_separator(passthrough: list[str]) -> list[str]:
    """Drop a leading ``--`` argparse left in the REMAINDER list."""
    if passthrough and passthrough[0] == "--":
        return passthrough[1:]
    return passthrough


def _extract_print_streaming_pair(argv: list[str]) -> tuple[list[str], bool]:
    """Pull ``--print-streaming-pair`` out of any position in ``argv``.

    ``passthrough`` uses ``nargs=argparse.REMAINDER``, which means the
    flag would otherwise reach the orchestrator verbatim if placed after
    the ``--`` separator. Pre-extracting makes every position equivalent.
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
    advance_args = _strip_separator(list(ns.passthrough))

    if _is_nested_advance_invocation(advance_args):
        print(NESTED_ADVANCE_REJECTION_MESSAGE, file=sys.stderr)
        return 2

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        _watch_runner.print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=advance_args,
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
        argv=_advance_argv(advance_args),
        classifier=classify_advance_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
