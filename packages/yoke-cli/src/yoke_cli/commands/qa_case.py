"""Client adapter for engine-owned materialized QA case execution."""

from __future__ import annotations

import signal
import subprocess
import sys
from typing import List


QA_CASE_RUN_USAGE = (
    "yoke qa case run --requirement-id N [--base-url URL] "
    "[--expected-branch BRANCH --expected-sha SHA] "
    "[--timeout-seconds N]"
)
QA_PLAN_RUN_USAGE = (
    "yoke qa plan run "
    "(--item PREFIX-N --transition TRANSITION | "
    "--deployment-run-id RUN --plan PLAN --project P) "
    "[--project P] [--base-url URL] "
    "[--expected-branch BRANCH --expected-sha SHA] "
    "[--timeout-seconds N] [--session-id S]"
)
QA_PLAN_ABORT_USAGE = (
    "yoke qa plan abort (--item PREFIX-N | --deployment-run-id RUN) "
    "--execution-id ID --reason TEXT [--project P] [--session-id S]"
)
QA_PLAN_REVIEW_SUBMIT_USAGE = (
    "yoke qa plan review-submit "
    "(--item-id N | --deployment-run-id RUN) --execution-id ID "
    "--bundle-id ID --bundle-digest SHA256 --stdin [--session-id S]"
)


def qa_case_run(args: List[str]) -> int:
    return _run_execution_module(
        "yoke_core.domain.qa_case_execution_cli",
        args,
    )


def qa_plan_run(args: List[str]) -> int:
    return _run_execution_module(
        "yoke_core.domain.qa_plan_execution_cli",
        args,
    )


def qa_plan_abort(args: List[str]) -> int:
    return _run_execution_module(
        "yoke_core.domain.qa_plan_execution_abort_cli",
        args,
    )


def qa_plan_review_submit(args: List[str]) -> int:
    return _run_execution_module(
        "yoke_core.domain.qa_plan_review_cli",
        args,
    )


def _run_execution_module(module: str, args: List[str]) -> int:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            module,
            *args,
        ],
        start_new_session=True,
    )
    try:
        return process.wait()
    except KeyboardInterrupt:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        previous_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            process.wait()
        finally:
            signal.signal(signal.SIGINT, previous_handler)
        return 128 + signal.SIGINT


TOOL_COMMANDS = {
    ("qa", "case", "run"): qa_case_run,
    ("qa", "plan", "abort"): qa_plan_abort,
    ("qa", "plan", "review-submit"): qa_plan_review_submit,
    ("qa", "plan", "run"): qa_plan_run,
}

USAGE = {
    "yoke qa case run": QA_CASE_RUN_USAGE,
    "yoke qa plan abort": QA_PLAN_ABORT_USAGE,
    "yoke qa plan review-submit": QA_PLAN_REVIEW_SUBMIT_USAGE,
    "yoke qa plan run": QA_PLAN_RUN_USAGE,
}


__all__ = [
    "QA_CASE_RUN_USAGE",
    "QA_PLAN_ABORT_USAGE",
    "QA_PLAN_RUN_USAGE",
    "QA_PLAN_REVIEW_SUBMIT_USAGE",
    "TOOL_COMMANDS",
    "USAGE",
    "qa_case_run",
    "qa_plan_abort",
    "qa_plan_review_submit",
    "qa_plan_run",
]
