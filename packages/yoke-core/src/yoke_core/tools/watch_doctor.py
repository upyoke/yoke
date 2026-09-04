"""Command-shaped watcher for ``yoke doctor run``.

Owns the doctor line classifier so callers do not author a Monitor
filter per invocation. Doctor can take many minutes when every HC is
enabled; without this wrapper agents hand-author capture redirections
and lose progress visibility (see the conduct evidence from
2026-05-14 where ``2>&1 > /tmp/log`` inverted the stream order and
sent stderr to the void).

The wrapped command is the transport-keyed one, so this is the single
doctor shape on every machine. Wrapping the engine entrypoint instead
made the wrapper useless exactly where an operator most needs progress:
that entrypoint opens the control-plane database itself, so on a
relayed machine it refused before running a single check and the
wrapper always exited 1. ``yoke doctor run`` relays control-plane checks,
runs source-tree checks locally, and streams a verdict line per check
either way. (``running HC-…`` comes only from checks this machine
executes — a relayed roster lives server-side, so the next check's name
is not known here until its verdict returns.)

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
    # is forwarded to `yoke doctor run`". Used by --print-streaming-pair.
    yoke watch doctor -- --quick

    # Bare form: unrecognized flags are also forwarded to doctor, so
    # ``-- --quick`` and bare ``--quick`` behave identically.
    yoke watch doctor --quick

    # Print the ready-to-paste streaming pair for Claude Code:
    yoke watch doctor --print-streaming-pair -- --quick

    # Explicit capture paths (used by --print-streaming-pair output):
    yoke watch doctor \\
        --raw-capture /tmp/raw.log --progress-capture /tmp/prog.log \\
        -- --quick

The wrapper preserves doctor's exit code so callers can still branch
on success/failure: 0 when the run recorded no FAIL, 1 when it did or
when the run itself failed, 2 when no scope flag was given.

Do NOT pass a full doctor command-shape (with or without the ``--``
separator). The wrapper rejects both ``yoke doctor run …`` and the
engine entrypoint ``python3 -m yoke_core.engines.doctor …`` (with its
``python``, ``sys.executable``, and ``pythonX.Y`` variants) before
invoking the underlying runner.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools import _watch_digest, _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_doctor"
KIND = "doctor"
#: The transport-keyed product command this wrapper runs. Invoked as a
#: module rather than through the ``yoke`` shim so the watcher's own
#: interpreter runs it — the one the CLI adapter already resolved (and
#: probed) as able to import this wrapper. ``yoke-core`` depends on
#: ``yoke-cli``, so an interpreter that imports the wrapper imports this
#: module too; there is no environment where one resolves and the other
#: does not.
DOCTOR_CLI_MODULE = "yoke_cli.main"
DOCTOR_CLI_SUBCOMMAND = ("doctor", "run")
# argparse prog for a direct module invocation; the CLI adapter
# passes the ``yoke watch doctor`` form so help reads back the
# command as typed.
DEFAULT_PROG = "watch_doctor"

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
    "do not restate the command itself. It rejects both "
    "`yoke doctor run …` and `python3 -m yoke_core.engines.doctor …`.\n"
    "Example: yoke watch doctor -- --quick"
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
    """Return True when pass-through ``args`` restate the command itself.

    Both spellings are caught: the ``yoke doctor run`` form an operator
    is most likely to paste after ``--``, and the engine entrypoint that
    still exists for source-dev use.
    """
    if list(args[:3]) == ["yoke", *DOCTOR_CLI_SUBCOMMAND]:
        return True
    if len(args) < 3:
        return False
    return (
        _looks_like_python_executable(args[0])
        and args[1] == "-m"
        and args[2] == "yoke_core.engines.doctor"
    )


def _doctor_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying doctor invocation."""
    return [
        sys.executable,
        "-m",
        DOCTOR_CLI_MODULE,
        *DOCTOR_CLI_SUBCOMMAND,
        *list(args),
    ]


HELP_EPILOG = """\
examples:
  yoke watch doctor -- --quick
      Canonical form. The ``--`` separator marks "everything after this
      is forwarded to doctor". This is the position emitted by
      --print-streaming-pair output.

  yoke watch doctor --quick
      Bare form. Unrecognized flags are forwarded to doctor too, so this
      behaves identically to ``-- --quick``.

  yoke watch doctor -- --full --project <project> --fix
      Operator-invoked full scan of another project, applying the
      deterministic repairs.

  yoke watch doctor -- --only HC-schema-drift
      Narrow to named checks.

  yoke watch doctor --print-streaming-pair -- --quick
      Select the safe wait: a reachable caller gets the background pair;
      a caller with no or unknown wake route stays in-turn until completion.

Scope is required: pass exactly one of ``--quick``, ``--full``, or
``--only <slug[,slug...]>``. ``--project NAME`` targets another project,
``--fix`` applies the deterministic repairs, and ``--file PATH`` also
writes the rendered report there.

Exit status is doctor's own: 0 when the run recorded no FAIL, 1 when it
did (or the run itself failed), 2 when no scope flag was given.

Do NOT restate the command in the passthrough — the wrapper supplies
``yoke doctor run`` and rejects both that form and the source-dev engine
entrypoint before any process starts.
"""


def _parse_args(
    argv: Sequence[str],
    prog: str = DEFAULT_PROG,
) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Run doctor under the shared raw+progress watcher wrapper.",
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


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw, print_streaming_pair_flag = _extract_print_streaming_pair(raw)
    raw, flush_seconds = _watch_digest.extract_flush_seconds(raw)
    ns, doctor_args = _parse_args(raw, prog)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True

    if _is_nested_doctor_invocation(doctor_args):
        print(NESTED_DOCTOR_REJECTION_MESSAGE, file=sys.stderr)
        return 2

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        return _watch_runner.run_or_print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=doctor_args,
            raw_capture=raw_path,
            progress_capture=progress_path,
            wrapper_options=_watch_digest.streaming_pair_options(flush_seconds),
        )

    raw_path, progress_path = _watch_runner.bind_capture_paths(ns, KIND)

    return _watch_runner.run_watcher(
        argv=_doctor_argv(doctor_args),
        classifier=classify_doctor_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
        flush_seconds=_watch_digest.resolve_flush_seconds(ns, flush_seconds),
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
