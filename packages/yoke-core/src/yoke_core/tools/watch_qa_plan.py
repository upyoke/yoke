"""Command-shaped watcher for ``yoke qa plan run``.

Owns the plan-run line classifier so callers do not author a Monitor
filter per invocation. A plan run is a long host-control sequence:
case boundaries, baseline transitions, operator gates, and frame
checkpoints arrive over minutes. Without a wrapper the caller falls
back to a hand-authored ``tail -f ... | grep``, which has no exit
sentinel.

KIND is ``qa_plan`` (word characters only). The exit sentinel
``watch_tail`` matches is ``^# watch_<kind> exit=<rc>``; a hyphen
here would leave every armed Monitor waiting. The CLI spells the
command ``yoke watch qa-plan``.

Usage::

    yoke watch qa-plan -- --item YOK-1 --transition implemented

    yoke watch qa-plan --print-streaming-pair -- --deployment-run-id RUN \\
        --plan PLAN --project P
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools import _watch_digest, _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_qa_plan"
KIND = "qa_plan"
DEFAULT_PROG = "watch_qa_plan"
PLAN_RUN_MODULE = "yoke_core.domain.qa_plan_execution_cli"

QA_PLAN_URGENT_RE = re.compile(
    r"(^yoke qa plan run:|TREE-BINDING REFUSAL|"
    r"status relay is temporarily unavailable)",
)
QA_PLAN_SUMMARY_RE = re.compile(
    r"(^#\s*qa plan run:|awaiting_agent_review|"
    r"QA capture complete|"
    r"^\{.*\"state\":)",
)
QA_PLAN_PROGRESS_RE = re.compile(
    r"(machine_qa\.operator_gate|"
    r"host_baseline|baseline=|"
    r"requirement=|case_key|"
    r"\"checkpoint\"|frame checkpoint|"
    r"Workflow status:)",
)

QA_PLAN_PROGRESS_PATTERN = re.compile(
    r"|".join(
        (
            QA_PLAN_URGENT_RE.pattern,
            QA_PLAN_SUMMARY_RE.pattern,
            QA_PLAN_PROGRESS_RE.pattern,
        )
    ),
)


def classify_qa_plan_line(line: str) -> Classification:
    """Classify one plan-run output line.

    URGENT first so a failure that also carries a plan token still
    emits immediately. SUMMARY before PROGRESS so the restated
    outcome and the ``awaiting_agent_review`` handoff are not
    throttled as ordinary progress.
    """
    if QA_PLAN_URGENT_RE.search(line):
        return Classification(LineClass.URGENT)
    if QA_PLAN_SUMMARY_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if QA_PLAN_PROGRESS_RE.search(line):
        return Classification(LineClass.PROGRESS)
    return Classification(LineClass.NOISE)


NESTED_INVOCATION_REJECTION_MESSAGE = (
    "watch_qa_plan expects bare `yoke qa plan run` flags after --; "
    "do not include the command itself.\n"
    "Example: yoke watch qa-plan -- --item YOK-1 --transition implemented"
)

_PYTHON_BASENAME_RE = re.compile(r"^python(\d+(\.\d+)?)?$")


def _looks_like_python_executable(token: str) -> bool:
    if token == "sys.executable":
        return True
    base = token.rsplit("/", 1)[-1]
    return bool(_PYTHON_BASENAME_RE.match(base))


def _is_nested_invocation(args: Sequence[str]) -> bool:
    if len(args) >= 3 and (
        _looks_like_python_executable(args[0])
        and args[1] == "-m"
        and args[2] == PLAN_RUN_MODULE
    ):
        return True
    return list(args[:4]) == ["yoke", "qa", "plan", "run"]


def _plan_run_argv(args: Sequence[str]) -> list[str]:
    return [sys.executable, "-m", PLAN_RUN_MODULE, *list(args)]


HELP_EPILOG = """\
examples:
  yoke watch qa-plan -- --item YOK-1 --transition implemented
      Canonical form. Everything after `--` is forwarded to the plan runner.

  yoke watch qa-plan --print-streaming-pair -- --item YOK-1 --transition implemented
      Select the safe wait: a reachable caller gets the background pair;
      a caller with no or unknown wake route stays in-turn until completion.

Do NOT restate the command in the passthrough — the wrapper supplies it
and rejects both `yoke qa plan run …` and the module form before any
process starts.
"""


def _parse_args(
    argv: Sequence[str],
    prog: str = DEFAULT_PROG,
) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=("Run a QA plan under the shared raw+progress watcher wrapper."),
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
        help="Explicit raw capture file path.",
    )
    parser.add_argument(
        "--progress-capture",
        type=Path,
        default=None,
        help="Explicit progress capture file path.",
    )
    ns, passthrough = parser.parse_known_args(list(argv))
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    return ns, passthrough


def _extract_print_streaming_pair(argv: list[str]) -> tuple[list[str], bool]:
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
    ns, plan_args = _parse_args(raw, prog)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True

    if _is_nested_invocation(plan_args):
        print(NESTED_INVOCATION_REJECTION_MESSAGE, file=sys.stderr)
        return 2

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        return _watch_runner.run_or_print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=plan_args,
            raw_capture=raw_path,
            progress_capture=progress_path,
            wrapper_options=_watch_digest.streaming_pair_options(flush_seconds),
        )

    raw_path, progress_path = _watch_runner.bind_capture_paths(ns, KIND)

    return _watch_runner.run_watcher(
        argv=_plan_run_argv(plan_args),
        classifier=classify_qa_plan_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
        flush_seconds=_watch_digest.resolve_flush_seconds(ns, flush_seconds),
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
