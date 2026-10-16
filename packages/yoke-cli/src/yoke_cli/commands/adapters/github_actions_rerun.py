"""Item-bound failed CI job rerun adapter."""

from __future__ import annotations

import argparse

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


GITHUB_ACTIONS_RERUN_FAILED_USAGE = (
    "yoke github-actions run rerun-failed ITEM RUN-ID [--session-id S] [--json]"
)


def github_actions_rerun_failed(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions run rerun-failed",
        description="Recover failed or cancelled CI on the claimed item's recorded PR, only at its current head and newest workflow run. Records intent and outcome in its Progress Log. Never-started jobs use a full rerun; started jobs use failed-job recovery. Cancellation stops at three total attempts: fix runner or workflow limits, then verify a fresh declared attempt. Resume the exact-head CI/QA wait; acceptance is not a pass.",
    )
    parser.add_argument("item", help="Claimed work item, e.g. PREFIX-N.")
    parser.add_argument(
        "run_id", help="Completed failed, timed-out or cancelled GitHub Actions run id."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_RERUN_FAILED_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="github_actions.run.rerun_failed",
        target=TargetRef(kind="item", public_ref=parsed.item),
        payload={"run_id": parsed.run_id},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
