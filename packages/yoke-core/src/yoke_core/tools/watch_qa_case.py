"""Command-shaped watcher for ``yoke qa case run`` — the QA gate.

Owns the gate-run line classifier so callers do not author a Monitor
filter per invocation. A gate run is one of the longest commands an agent
issues: routed to CI it polls a workflow for 13-14 minutes, and run
locally it streams a full suite. Without a wrapper the caller falls back
to a hand-authored ``tail -f ... | grep``, which has no exit sentinel —
so the paired Monitor never self-terminates and keeps running long after
the gate finishes.

The classifier maps:

- The engine's own failure line (``yoke qa case run: ...``), a
  tree-binding refusal, and the degraded-relay retry notice → ``URGENT``.
- ``Workflow status: <state> (elapsed: Ns, next poll: Ns)`` CI polls →
  ``PROGRESS`` (time-window throttled).
- The restated outcome (``# qa case run: verdict=...``) and the final
  result envelope → ``SUMMARY``.

Anything the gate-specific patterns miss falls through to the pytest
classifier, because a locally-executed case streams its command's output
verbatim and that command is usually pytest. Reusing that classifier
keeps one owner for the pytest line shapes rather than a second copy that
drifts.

Usage::

    yoke watch qa-case -- --requirement-id 10194

    # Bare form: unrecognized flags are forwarded too, so this behaves
    # identically to the ``--`` form.
    yoke watch qa-case --requirement-id 10194

    # Print the ready-to-paste streaming pair:
    yoke watch qa-case --print-streaming-pair -- --requirement-id 10194

The wrapper preserves the gate's exit code, including the distinct
``waiting`` retry status the case runner reports when a dispatched run
has not settled.

Do NOT pass a full command-shape after ``--``. The wrapper rejects both
``yoke qa case run …`` and the module form before any process starts.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_pytest_classify import classify_pytest_line
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_qa_case"
# ``\w+`` only: the exit sentinel watch_tail matches is
# ``^# watch_<kind> exit=<rc>``, so a hyphen here would leave every
# armed Monitor waiting forever — the exact failure this wrapper exists
# to remove. The CLI spells the command ``yoke watch qa-case``.
KIND = "qa_case"
# argparse prog for a direct module invocation; the CLI adapter passes
# the ``yoke watch qa-case`` form so help reads back the command as typed.
DEFAULT_PROG = "watch_qa_case"

CASE_RUN_MODULE = "yoke_core.domain.qa_case_execution_cli"

# Per-class regexes. Each is line-oriented; callers feed one line at a
# time. Separate constants let tests exercise each class independently.
QA_CASE_URGENT_RE = re.compile(
    r"(^yoke qa case run:|TREE-BINDING REFUSAL|"
    r"status relay is temporarily unavailable)",
)
QA_CASE_PROGRESS_RE = re.compile(r"^\s*Workflow status:\s*\S+")
# The restated outcome line, then the machine-readable envelope the gate
# prints last. The envelope is matched by its verdict key rather than its
# first key, which is only ``artifact_id`` for the runners that produce
# artifacts.
QA_CASE_SUMMARY_RE = re.compile(
    r"(^#\s*qa case run:|^\{.*\"verdict\":)",
)

# Public union pattern: one "is this a gate signal line?" check for
# callers and tests, composed from the per-class regexes so each shape
# has exactly one source of truth.
QA_CASE_PROGRESS_PATTERN = re.compile(
    r"|".join(
        (
            QA_CASE_URGENT_RE.pattern,
            QA_CASE_PROGRESS_RE.pattern,
            QA_CASE_SUMMARY_RE.pattern,
        )
    ),
)


def classify_qa_case_line(line: str) -> Classification:
    """Classify a single gate-run output line.

    Order matters: a failure line that also carries a gate token must
    still emit immediately, so URGENT is checked first and SUMMARY
    before PROGRESS.

    A line matching none of the gate shapes is handed to the pytest
    classifier: a locally-executed case streams its command's output
    through this same stream, and that command is usually pytest. The
    pytest classifier answers ``NOISE`` for anything it does not
    recognize, which is the right answer here too.
    """
    if QA_CASE_URGENT_RE.search(line):
        return Classification(LineClass.URGENT)
    if QA_CASE_SUMMARY_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if QA_CASE_PROGRESS_RE.search(line):
        return Classification(LineClass.PROGRESS)
    return classify_pytest_line(line)


NESTED_INVOCATION_REJECTION_MESSAGE = (
    "watch_qa_case expects bare `yoke qa case run` flags after --; "
    "do not include the command itself.\n"
    "Example: yoke watch qa-case -- --requirement-id 10194"
)

# Match the bare interpreter names operators most commonly retype, plus
# the literal ``sys.executable`` token. Path forms
# (``/usr/bin/python3``) reuse this against the basename.
_PYTHON_BASENAME_RE = re.compile(r"^python(\d+(\.\d+)?)?$")


def _looks_like_python_executable(token: str) -> bool:
    """Return True when ``token`` names a Python interpreter."""
    if token == "sys.executable":
        return True
    base = token.rsplit("/", 1)[-1]
    return bool(_PYTHON_BASENAME_RE.match(base))


def _is_nested_invocation(args: Sequence[str]) -> bool:
    """Return True when pass-through ``args`` restate the command itself.

    Both spellings are caught: the module form the wrapper supplies
    internally, and the ``yoke qa case run`` form an operator is far more
    likely to paste after ``--``.
    """
    if len(args) >= 3 and (
        _looks_like_python_executable(args[0])
        and args[1] == "-m"
        and args[2] == CASE_RUN_MODULE
    ):
        return True
    return list(args[:4]) == ["yoke", "qa", "case", "run"]


def _case_run_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying gate invocation."""
    return [sys.executable, "-m", CASE_RUN_MODULE, *list(args)]


HELP_EPILOG = """\
examples:
  yoke watch qa-case -- --requirement-id 10194
      Canonical form. The ``--`` separator marks "everything after this
      is forwarded to the gate". This is the position emitted by
      --print-streaming-pair output.

  yoke watch qa-case --requirement-id 10194
      Bare form. Unrecognized flags are forwarded too, so this behaves
      identically to the ``--`` form.

  yoke watch qa-case --print-streaming-pair -- --requirement-id 10194
      Print a ready-to-paste background command + progress-tail pair
      and exit.

Do NOT restate the command in the passthrough — the wrapper supplies it
and rejects both `yoke qa case run …` and the module form before any
process starts.
"""


def _parse_args(
    argv: Sequence[str], prog: str = DEFAULT_PROG,
) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Run the QA gate under the shared raw+progress watcher wrapper."
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
    # Unknown flags (``--requirement-id``, ``--base-url``, …) are forwarded
    # to the gate as passthrough. The ``--`` separator is consumed by
    # argparse and is the canonical position used by
    # --print-streaming-pair.
    ns, passthrough = parser.parse_known_args(list(argv))
    # Defensive: drop a leading ``--`` if argparse left one in the list.
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    return ns, passthrough


def _extract_print_streaming_pair(argv: list[str]) -> tuple[list[str], bool]:
    """Pull ``--print-streaming-pair`` out of any position in ``argv``."""
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
    ns, case_args = _parse_args(raw, prog)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True

    if _is_nested_invocation(case_args):
        print(NESTED_INVOCATION_REJECTION_MESSAGE, file=sys.stderr)
        return 2

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        _watch_runner.print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=case_args,
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
        argv=_case_run_argv(case_args),
        classifier=classify_qa_case_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
