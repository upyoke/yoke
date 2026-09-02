"""Client adapter for engine-owned materialized QA case execution."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import List, Tuple

from yoke_cli.transport.dispatcher import build_actor


_QA_MISSION_HOST_COMMAND_MODULE = "yoke_core.domain.agent_mission_host_command_cli"
_QA_MISSION_SCRATCH_MODULE = "yoke_core.domain.agent_mission_scratch_cli"


QA_CASE_RUN_USAGE = (
    "yoke qa case run --requirement-id N [--base-url URL] "
    "[--expected-branch BRANCH --expected-sha SHA] "
    "[--timeout-seconds N] [--allow-tree-mismatch] [--session-id S]"
)
QA_PLAN_RUN_USAGE = (
    "yoke qa plan run "
    "(--item PREFIX-N --transition TRANSITION | "
    "--deployment-run-id RUN --plan PLAN --project P) "
    "[--project P] [--base-url URL] [--machine NAME] "
    "[--expected-branch BRANCH --expected-sha SHA] "
    "[--timeout-seconds N] [--allow-tree-mismatch] [--continue-mission] "
    "[--session-id S]"
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
QA_MISSION_HOST_COMMAND_USAGE = (
    "yoke qa mission host-command "
    "(--item PREFIX-N | --item-id N | --deployment-run-id RUN) "
    "--execution-id ID --requirement-id N [--gui-session] "
    "[--timeout-seconds N] -- ARGV..."
)
QA_MISSION_SCRATCH_TEARDOWN_USAGE = (
    "yoke qa mission scratch-teardown "
    "(--item PREFIX-N | --item-id N | --deployment-run-id RUN) "
    "--execution-id ID --requirement-id N [--timeout-seconds N]"
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


def qa_mission_host_command(args: List[str]) -> int:
    return _run_execution_module(
        _QA_MISSION_HOST_COMMAND_MODULE,
        args,
    )


def qa_mission_scratch_teardown(args: List[str]) -> int:
    return _run_execution_module(
        _QA_MISSION_SCRATCH_MODULE,
        args,
    )


def _pin_execution_session(args: List[str]) -> Tuple[List[str], str]:
    """Resolve the QA actor without changing the detached child's argv."""
    for index, value in enumerate(args):
        if value == "--session-id":
            return list(args), args[index + 1] if index + 1 < len(args) else ""
        if value.startswith("--session-id="):
            return list(args), value.partition("=")[2]
    session_id = build_actor().session_id
    if not session_id:
        return list(args), ""
    return list(args), session_id


def _assert_unmodified_host_command_args(
    requested_args: List[str],
    forwarded_args: List[str],
) -> None:
    if forwarded_args == requested_args:
        return
    difference = next(
        (
            index
            for index, (requested, forwarded) in enumerate(
                zip(requested_args, forwarded_args)
            )
            if requested != forwarded
        ),
        min(len(requested_args), len(forwarded_args)),
    )
    forwarded = (
        forwarded_args[difference] if difference < len(forwarded_args) else "<missing>"
    )
    preview = forwarded if len(forwarded) <= 120 else f"{forwarded[:117]}..."
    raise RuntimeError(
        "yoke qa mission host-command refused argv mutation at index "
        f"{difference}: forwarded {preview!r}"
    )


def _run_execution_module(
    module: str,
    args: List[str],
) -> int:
    requested_args = list(args)
    child_args, session_id = _pin_execution_session(list(requested_args))
    if module == _QA_MISSION_HOST_COMMAND_MODULE:
        _assert_unmodified_host_command_args(requested_args, child_args)
    popen_kwargs = {"start_new_session": True}
    if session_id:
        child_env = dict(os.environ)
        child_env["YOKE_SESSION_ID"] = session_id
        popen_kwargs["env"] = child_env
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            module,
            *child_args,
        ],
        **popen_kwargs,
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
    ("qa", "mission", "host-command"): qa_mission_host_command,
    ("qa", "mission", "scratch-teardown"): qa_mission_scratch_teardown,
}

USAGE = {
    "yoke qa case run": QA_CASE_RUN_USAGE,
    "yoke qa plan abort": QA_PLAN_ABORT_USAGE,
    "yoke qa plan review-submit": QA_PLAN_REVIEW_SUBMIT_USAGE,
    "yoke qa plan run": QA_PLAN_RUN_USAGE,
    "yoke qa mission host-command": QA_MISSION_HOST_COMMAND_USAGE,
    "yoke qa mission scratch-teardown": QA_MISSION_SCRATCH_TEARDOWN_USAGE,
}


__all__ = [
    "QA_CASE_RUN_USAGE",
    "QA_PLAN_ABORT_USAGE",
    "QA_PLAN_RUN_USAGE",
    "QA_PLAN_REVIEW_SUBMIT_USAGE",
    "QA_MISSION_HOST_COMMAND_USAGE",
    "QA_MISSION_SCRATCH_TEARDOWN_USAGE",
    "TOOL_COMMANDS",
    "USAGE",
    "qa_case_run",
    "qa_mission_host_command",
    "qa_mission_scratch_teardown",
    "qa_plan_abort",
    "qa_plan_review_submit",
    "qa_plan_run",
]
