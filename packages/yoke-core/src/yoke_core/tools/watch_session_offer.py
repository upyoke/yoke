"""Command-shaped watcher for ``yoke_core.api.service_client session-offer`` runs.

Owns the session-offer line classifier so callers do not author a
Monitor filter per invocation. The session-offer path runs frontier
construction, lane filtering, drift assessment, and decision rendering
(50-97s observed in live sessions on a large frontier). The command is
mostly silent during the compute and emits its verdict as a single
JSON envelope on stdout; the wrapper surfaces that envelope as a
SUMMARY line and flags ``Error:`` / ``Usage:`` lines as URGENT.

Class assignments:

- ``Error:`` / ``ERROR:`` / ``Usage:`` / ``Warning:`` lines → ``URGENT``.
- ``HarnessSessionOffered``, ``NextActionChosen``, and other narrative
  banners emitted during compute → ``SUMMARY``.
- The final ``NextAction`` JSON envelope on stdout — a single line
  starting with ``{"action":`` — → ``SUMMARY``.

Every other line is ``NOISE`` (raw capture only). Session-offer rarely
emits intermediate progress lines, so the PROGRESS class is reserved
for future enrichment of the underlying engine; for now only URGENT
and SUMMARY fire.

Usage::

    # Direct execution (Codex / shell): streams filtered progress to
    # stdout while preserving full output in the raw capture. Pass any
    # session-offer flags after ``--``; the wrapper supplies the
    # ``python3 -m yoke_core.api.service_client session-offer`` prefix.
    python3 -m yoke_core.tools.watch_session_offer -- \\
        --executor claude-code --provider anthropic \\
        --workspace /repo --step 1

    # Print the ready-to-paste streaming pair for Claude Code:
    python3 -m yoke_core.tools.watch_session_offer --print-streaming-pair -- \\
        --executor claude-code --provider anthropic --workspace /repo --step 1

The wrapper preserves session-offer's exit code so callers can still
branch on success/failure.

Do NOT pass a full session-offer command-shape after ``--``. The
wrapper rejects ``-- python3 -m yoke_core.api.service_client session-offer …``
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

WRAPPER_MODULE = "yoke_core.tools.watch_session_offer"
KIND = "session-offer"
UNDERLYING_MODULE = "yoke_core.api.service_client"
UNDERLYING_SUBCOMMAND = "session-offer"


# Per-class regexes. Each is line-oriented; callers feed one line at a
# time.
SESSION_OFFER_URGENT_RE = re.compile(
    r"^(Error:|ERROR:|Usage:|Warning:)",
)
SESSION_OFFER_SUMMARY_NARRATIVE_RE = re.compile(
    r"^(HarnessSessionOffered|NextActionChosen|SchedulerOfferSkipped|"
    r"SessionOfferLaneOverrideIgnored|=== )",
)
# Final NextAction envelope: single line starting with ``{"action":``.
SESSION_OFFER_SUMMARY_JSON_RE = re.compile(r'^\{"action":')


# Public union pattern: kept for callers/tests that want a single
# "is this a signal line?" check. Composed from the per-class regexes
# above so there is exactly one source of truth for each shape.
SESSION_OFFER_PROGRESS_PATTERN = re.compile(
    r"|".join(
        (
            SESSION_OFFER_URGENT_RE.pattern,
            SESSION_OFFER_SUMMARY_NARRATIVE_RE.pattern,
            SESSION_OFFER_SUMMARY_JSON_RE.pattern,
        )
    )
)


def classify_session_offer_line(line: str) -> Classification:
    """Classify a single session-offer output line.

    Order matters: failure lines that *also* contain other tokens must
    still classify as ``URGENT`` so they emit immediately. We check
    URGENT before the SUMMARY regexes for that reason.
    """
    if SESSION_OFFER_URGENT_RE.search(line):
        return Classification(LineClass.URGENT)
    if SESSION_OFFER_SUMMARY_NARRATIVE_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if SESSION_OFFER_SUMMARY_JSON_RE.search(line):
        return Classification(LineClass.SUMMARY)
    return Classification(LineClass.NOISE)


NESTED_SESSION_OFFER_REJECTION_MESSAGE = (
    "watch_session_offer expects bare session-offer args after --; "
    f"do not include python3 -m {UNDERLYING_MODULE} {UNDERLYING_SUBCOMMAND}.\n"
    "Example: python3 -m yoke_core.tools.watch_session_offer -- "
    "--executor claude-code --provider anthropic --workspace /repo"
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


def _is_nested_session_offer_invocation(args: Sequence[str]) -> bool:
    """Return True if pass-through ``args`` start with
    ``<python> -m yoke_core.api.service_client session-offer``.
    """
    if len(args) < 4:
        return False
    return (
        _looks_like_python_executable(args[0])
        and args[1] == "-m"
        and args[2] == UNDERLYING_MODULE
        and args[3] == UNDERLYING_SUBCOMMAND
    )


def _session_offer_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying session-offer invocation."""
    return [
        sys.executable, "-m", UNDERLYING_MODULE, UNDERLYING_SUBCOMMAND,
        *list(args),
    ]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watch_session_offer",
        description=(
            "Run service_client session-offer under the shared "
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
            "Bare session-offer arguments. Use ``--`` to separate "
            "wrapper flags from session-offer flags. Do NOT include "
            f"``python3 -m {UNDERLYING_MODULE} {UNDERLYING_SUBCOMMAND}``; "
            "the wrapper supplies that prefix."
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
    flag would otherwise reach session-offer verbatim if placed after
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
    session_offer_args = _strip_separator(list(ns.passthrough))

    if _is_nested_session_offer_invocation(session_offer_args):
        print(NESTED_SESSION_OFFER_REJECTION_MESSAGE, file=sys.stderr)
        return 2

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        _watch_runner.print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=session_offer_args,
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
        argv=_session_offer_argv(session_offer_args),
        classifier=classify_session_offer_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
