"""Client adapter for engine-owned materialized QA case execution."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import List, Tuple

from yoke_cli.commands._helpers import show_delegate_help
from yoke_cli.transport.dispatcher import build_actor


QA_MISSION_HOST_COMMAND_MODULE = "yoke_core.domain.agent_mission_host_command_cli"


QA_CASE_RUN_USAGE = (
    "yoke qa case run --requirement-id N [--base-url URL] "
    "[--expected-branch BRANCH --expected-sha SHA] "
    "[--timeout-seconds N] [--checkout-path PATH] "
    "[--allow-tree-mismatch] [--session-id S]"
)
QA_PLAN_RUN_USAGE = (
    "yoke qa plan run "
    "(--item PREFIX-N (--transition TRANSITION | --stage STAGE) | "
    "--deployment-run-id RUN --stage STAGE [--plan PLAN] | "
    "--plan PLAN --project P | --resume-execution-id ID) [--replaces CASE_KEY=REQUIREMENT_ID] "
    "[--project P] [--base-url URL] [--test-machine TEST_MACHINE] "
    "[--expected-branch BRANCH --expected-sha SHA] "
    "[--timeout-seconds N] [--checkout-path PATH] "
    "[--allow-tree-mismatch] [--continue-mission] "
    "[--session-id S]"
)
QA_PLAN_ADOPT_USAGE = (
    "yoke qa plan adopt [--item PREFIX-N] "
    "--execution-id ID --reason TEXT [--session-id S] [--json]"
)
QA_PLAN_RECONCILE_USAGE = (
    "yoke qa plan reconcile --project P --execution-id ID --reason TEXT "
    "[--session-id S] [--json]"
)
QA_PLAN_ABORT_USAGE = (
    "yoke qa plan abort [--item PREFIX-N | --project P] "
    "--execution-id ID --reason TEXT [--project P] [--session-id S]"
)
QA_PLAN_REVIEW_SUBMIT_USAGE = (
    "yoke qa plan review-submit "
    "[--item PREFIX-N] --execution-id ID "
    "--bundle-id ID --bundle-digest SHA256 --stdin [--session-id S]"
)
QA_PLAN_REVIEW_BEGIN_USAGE = (
    "yoke qa plan review-begin [--item PREFIX-N | --project P] "
    "--execution-id ID [--session-id S] [--json]"
)


def qa_case_run(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_CASE_RUN_USAGE,
        "Requires the named immutable QA case and matching item/task work claim. "
        "A mission starts a one-requirement plan execution; exit 12 hands its typed review to the main agent. "
        "With multiple lanes, select --checkout-path PATH --expected-branch BRANCH "
        "--expected-sha FULL_SHA; CI refuses source mismatches before publication.",
    ):
        return 0
    return run_execution_module(
        "yoke_core.domain.qa_case_execution_cli",
        args,
    )


def qa_plan_run(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_PLAN_RUN_USAGE,
        "Requires the named immutable QA case or execution; item cases require the item work claim. "
        "At an item-scoped stage, --deployment-run-id RUN --plan P runs the run's open plan group of P; "
        "with none open it refuses plan_group_not_open and lists P's closed groups. "
        "At a run-scoped stage, a new plan fills only an empty stage. "
        "Host selection respects the case OS. Resume and correction commands omit --test-machine; "
        "the scheduler retains each platform's or corrected case's recorded host.\n\n"
        "Failed member QA: inspect the failed requirement and run, then classify product, setup, "
        "case or unclear cause. Fix a finding in this item there. Record a closure dependency only "
        "when a finding is in this item and another item must land first; name its owner: fact:merged "
        "when that fix ships in the same release, status:done for completion, "
        "fact:deployed:ENV only when the fix must be live before this item's release. "
        "Checkpoint the failure, exact milestone and next command; keep the claim and lane. "
        "Steering staffs and delivers corrections and arranges supported manual resume when needed. "
        "Reread all blockers and the deployed target on resume; a dependency notice cannot "
        "retarget a frozen run. Run scoped QA on a candidate containing the fix.\n"
        "Complete recovery: .yoke/docs/verification/failed-item-qa.md "
        "(source: docs/public/verification/failed-item-qa.md).",
    ):
        return 0
    return run_execution_module(
        "yoke_core.domain.qa_plan_execution_cli",
        args,
    )


def qa_plan_adopt(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_PLAN_ADOPT_USAGE,
        "Requires the execution item's current work claim and an ended predecessor session. "
        "Preserves captured evidence; retry review-begin or the exact execution resume command after adoption.",
    ):
        return 0
    return run_execution_module("yoke_core.domain.qa_plan_execution_adopt_cli", args)


def qa_plan_reconcile(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_PLAN_RECONCILE_USAGE,
        "Operator recovery for an execution whose owner stopped reporting or whose "
        "recovery receipt is invalid. A session needs the execution item's current "
        "work claim or a live steering seat covering the project; otherwise "
        "steering_seat_required names both routes. Never "
        "settles an active walk (use yoke qa plan abort) or a parked owner's walk. "
        "A held host lease needs recorded recovery first: the refusal names the "
        "exact reset or release command. A judgeable pending review passes to the "
        "caller and the receipt names its review-begin; otherwise the execution "
        "settles as aborted with no verdict. Every run writes a reconciliation "
        "receipt.",
    ):
        return 0
    return run_execution_module(
        "yoke_core.domain.qa_plan_execution_reconcile_cli", args
    )


def qa_plan_abort(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_PLAN_ABORT_USAGE,
        "Requires the named immutable QA case or execution; item cases require the item work claim. "
        "--reason holds at most 200 characters: a code and a short diagnosis; "
        "cite the Progress Log or an artifact for the full rationale.",
    ):
        return 0
    return run_execution_module(
        "yoke_core.domain.qa_plan_execution_abort_cli",
        args,
    )


def qa_plan_review_submit(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_PLAN_REVIEW_SUBMIT_USAGE,
        "Requires the named immutable QA case or execution; item cases require the item work claim.",
    ):
        return 0
    return run_execution_module(
        "yoke_core.domain.qa_plan_review_cli",
        args,
    )


def qa_plan_review_begin(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_PLAN_REVIEW_BEGIN_USAGE,
        "Retrieve completed captures, then use the returned review-submit command. "
        "An aborted or errored execution remains terminal after review.",
    ):
        return 0
    return run_execution_module("yoke_core.domain.qa_plan_review_begin_cli", args)


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


def run_execution_module(
    module: str,
    args: List[str],
) -> int:
    requested_args = list(args)
    child_args, session_id = _pin_execution_session(list(requested_args))
    if module == QA_MISSION_HOST_COMMAND_MODULE:
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
    ("qa", "plan", "adopt"): qa_plan_adopt,
    ("qa", "plan", "reconcile"): qa_plan_reconcile,
    ("qa", "plan", "review-submit"): qa_plan_review_submit,
    ("qa", "plan", "review-begin"): qa_plan_review_begin,
    ("qa", "plan", "run"): qa_plan_run,
}

USAGE = {
    "yoke qa case run": QA_CASE_RUN_USAGE,
    "yoke qa plan abort": QA_PLAN_ABORT_USAGE,
    "yoke qa plan adopt": QA_PLAN_ADOPT_USAGE,
    "yoke qa plan reconcile": QA_PLAN_RECONCILE_USAGE,
    "yoke qa plan review-submit": QA_PLAN_REVIEW_SUBMIT_USAGE,
    "yoke qa plan review-begin": QA_PLAN_REVIEW_BEGIN_USAGE,
    "yoke qa plan run": QA_PLAN_RUN_USAGE,
}


__all__ = [
    "QA_PLAN_REVIEW_BEGIN_USAGE",
    "qa_plan_review_begin",
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
