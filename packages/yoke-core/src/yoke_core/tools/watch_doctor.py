"""Command-shaped watcher for ``yoke_core.engines.doctor`` runs.

Owns the doctor line classifier so callers do not author a Monitor
filter per invocation. Doctor can take many minutes when every HC is
enabled; without this wrapper agents hand-author capture redirections
and lose progress visibility (see the conduct evidence from
2026-05-14 where ``2>&1 > /tmp/log`` inverted the stream order and
sent stderr to the void).

The classifier maps:

- ``HC-<name>: FAIL`` / ``HC-<name>: ERROR`` per-check failure lines
  → ``URGENT`` (immediate emit).
- ``HC-<name>: PASS`` / ``HC-<name>: WARN`` per-check terminal lines
  → ``PROGRESS`` (one tick per completed check).
- ``running HC-<name>`` per-check start lines → ``PROGRESS``.
- ``# Ouroboros Health Report`` header and ``N checks run`` summary
  lines → ``SUMMARY``.

Every other line is ``NOISE`` (raw capture only).

Usage::

    # Canonical form: the ``--`` separator marks "everything after this
    # is forwarded to doctor". Used by --print-streaming-pair output.
    python3 -m yoke_core.tools.watch_doctor -- --quick

    # Bare form: unrecognized flags are also forwarded to doctor, so
    # ``-- --quick`` and bare ``--quick`` behave identically.
    python3 -m yoke_core.tools.watch_doctor --quick

    # Print the ready-to-paste streaming pair for Claude Code:
    python3 -m yoke_core.tools.watch_doctor --print-streaming-pair -- --quick

    # Explicit capture paths (used by --print-streaming-pair output):
    python3 -m yoke_core.tools.watch_doctor \\
        --raw-capture /tmp/raw.log --progress-capture /tmp/prog.log \\
        -- --quick

The wrapper preserves doctor's exit code so callers can still branch
on success/failure.

Do NOT pass a full doctor command-shape (with or without the ``--``
separator). The wrapper rejects ``python3 -m yoke_core.engines.doctor
…`` (and the ``python``, ``sys.executable``, and ``pythonX.Y``
variants) before invoking the underlying runner.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_doctor"
KIND = "doctor"

# Per-class regexes. Each is line-oriented; callers feed one line at a
# time. Keeping them as separate constants lets tests exercise each
# class independently without re-parsing the union pattern.
DOCTOR_URGENT_RE = re.compile(r"HC-\S+:\s*(FAIL|ERROR)\b", re.IGNORECASE)
DOCTOR_PROGRESS_RE = re.compile(
    r"(HC-\S+:\s*(PASS|WARN|SKIP)\b|^\s*running\s+HC-\S+)",
    re.IGNORECASE,
)
DOCTOR_SUMMARY_BANNER_RE = re.compile(
    r"(^# Ouroboros Health Report\b|^\d+ checks run\b)",
    re.IGNORECASE,
)

# Public union pattern: kept for callers/tests that want a single
# "is this a signal line?" check. Composed from the per-class regexes
# above so there is exactly one source of truth for each shape.
DOCTOR_PROGRESS_PATTERN = re.compile(
    r"|".join(
        (
            DOCTOR_URGENT_RE.pattern,
            DOCTOR_PROGRESS_RE.pattern,
            DOCTOR_SUMMARY_BANNER_RE.pattern,
        )
    ),
    re.IGNORECASE,
)


def classify_doctor_line(line: str) -> Classification:
    """Classify a single doctor output line.

    Order matters: failure lines that *also* contain other tokens must
    still classify as ``URGENT`` so they emit immediately. We check
    URGENT and SUMMARY before PROGRESS for that reason.
    """
    if DOCTOR_URGENT_RE.search(line):
        return Classification(LineClass.URGENT)
    if DOCTOR_SUMMARY_BANNER_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if DOCTOR_PROGRESS_RE.search(line):
        return Classification(LineClass.PROGRESS)
    return Classification(LineClass.NOISE)


NESTED_DOCTOR_REJECTION_MESSAGE = (
    "watch_doctor expects bare doctor args after --; "
    "do not include python3 -m yoke_core.engines.doctor.\n"
    "Example: python3 -m yoke_core.tools.watch_doctor -- --quick"
)

# Match the bare interpreter names operators most commonly retype, plus
# the literal ``sys.executable`` token (sometimes copied from the wrapper
# source). Path forms (``/usr/bin/python3``) reuse this against the
# basename so we accept them without separately enumerating prefixes.
_PYTHON_BASENAME_RE = re.compile(r"^python(\d+(\.\d+)?)?$")


def _looks_like_python_executable(token: str) -> bool:
    """Return True when ``token`` names a Python interpreter."""
    if token == "sys.executable":
        return True
    base = token.rsplit("/", 1)[-1]
    return bool(_PYTHON_BASENAME_RE.match(base))


def _is_nested_doctor_invocation(args: Sequence[str]) -> bool:
    """Return True if pass-through ``args`` start with
    ``<python> -m yoke_core.engines.doctor``."""
    if len(args) < 3:
        return False
    return (
        _looks_like_python_executable(args[0])
        and args[1] == "-m"
        and args[2] == "yoke_core.engines.doctor"
    )


def _doctor_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying doctor invocation."""
    return [sys.executable, "-m", "yoke_core.engines.doctor", *list(args)]


HELP_EPILOG = """\
examples:
  python3 -m yoke_core.tools.watch_doctor -- --quick
      Canonical form. The ``--`` separator marks "everything after this
      is forwarded to doctor". This is the position emitted by
      --print-streaming-pair output.

  python3 -m yoke_core.tools.watch_doctor --quick
      Bare form. Unrecognized flags are forwarded to doctor too, so this
      behaves identically to ``-- --quick``.

  python3 -m yoke_core.tools.watch_doctor --print-streaming-pair -- --quick
      Print a ready-to-paste background command + progress-tail pair
      and exit.

Do NOT include ``python3 -m yoke_core.engines.doctor`` in the
passthrough — the wrapper supplies that prefix and rejects nested
doctor invocations before any process starts.
"""


def _parse_args(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="watch_doctor",
        description="Run doctor under the shared raw+progress watcher wrapper.",
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
    # Unknown flags (e.g. ``--quick``, ``--check HC-foo``) are forwarded to
    # doctor as passthrough. The ``--`` separator is consumed by argparse and
    # is supported as the canonical position used by --print-streaming-pair.
    ns, passthrough = parser.parse_known_args(list(argv))
    # Defensive: drop a leading ``--`` if argparse left one in the list.
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    return ns, passthrough


def _extract_print_streaming_pair(argv: list[str]) -> tuple[list[str], bool]:
    """Pull ``--print-streaming-pair`` out of any position in ``argv``.

    ``passthrough`` uses ``nargs=argparse.REMAINDER``, which means the
    flag would otherwise reach doctor verbatim if placed after the
    ``--`` separator. Pre-extracting makes every position equivalent.
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
    ns, doctor_args = _parse_args(raw)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True

    if _is_nested_doctor_invocation(doctor_args):
        print(NESTED_DOCTOR_REJECTION_MESSAGE, file=sys.stderr)
        return 2

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        _watch_runner.print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=doctor_args,
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
        argv=_doctor_argv(doctor_args),
        classifier=classify_doctor_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
