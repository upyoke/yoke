"""Client adapter for engine-owned materialized QA case execution."""

from __future__ import annotations

import subprocess
import sys
from typing import List


QA_CASE_RUN_USAGE = (
    "yoke qa case run --requirement-id N [--base-url URL] "
    "[--expected-branch BRANCH --expected-sha SHA] "
    "[--timeout-seconds N]"
)
QA_PLAN_RUN_USAGE = (
    "yoke qa plan run --item PREFIX-N --transition TRANSITION "
    "[--project P] [--base-url URL] "
    "[--expected-branch BRANCH --expected-sha SHA] "
    "[--timeout-seconds N] [--session-id S]"
)


def qa_case_run(args: List[str]) -> int:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.domain.qa_case_execution_cli",
            *args,
        ],
        check=False,
    )
    return completed.returncode


def qa_plan_run(args: List[str]) -> int:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.domain.qa_plan_execution_cli",
            *args,
        ],
        check=False,
    )
    return completed.returncode


TOOL_COMMANDS = {
    ("qa", "case", "run"): qa_case_run,
    ("qa", "plan", "run"): qa_plan_run,
}

USAGE = {
    "yoke qa case run": QA_CASE_RUN_USAGE,
    "yoke qa plan run": QA_PLAN_RUN_USAGE,
}


__all__ = [
    "QA_CASE_RUN_USAGE",
    "QA_PLAN_RUN_USAGE",
    "TOOL_COMMANDS",
    "USAGE",
    "qa_case_run",
    "qa_plan_run",
]
