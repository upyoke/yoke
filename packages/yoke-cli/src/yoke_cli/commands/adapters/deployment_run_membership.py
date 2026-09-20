"""Deployment-run membership and composition CLI adapters."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


ADD_ITEM_USAGE = (
    "yoke deployment-runs add-item RUN-ID PREFIX-N "
    "[--project P] [--intent progress|final] [--requirement-id N ...] "
    "[--plan-id N ...] [--session-id S] [--json]"
)
VALIDATE_COMPOSITION_USAGE = (
    "yoke deployment-runs validate-composition RUN-ID [--session-id S] [--json]"
)

# A run ships code for more than its own project, and the membership rule
# follows the code. Name where the boundary now is, at the refusal.
CROSS_PROJECT_MEMBERSHIP_NOTE = """\
Membership follows the source the run ships:
  An item may join a run whose project owns it, or whose flow binds that
  item's project through a stage `input_bindings`. The run resolves each
  bound branch once at start and records the commit, so a bound project's
  delivery-ready items are enrolled against that exact commit and closed out
  by the run that actually shipped them. Check what a flow binds with
  `yoke deployment-flows stages FLOW-ID`, and what a run recorded with
  `yoke deployment-runs get RUN-ID`.

  An item whose project the run ships no source for is refused: no membership
  row, no requirement snapshot, no deployment wake. It stays at its release
  wait until a run that does ship its code carries it.

What the run can do for the member, named on every add:
  Two independent capabilities, and a run can have either, both, or neither.
  It CHECKS a member only through an item-scoped QA stage — that is what runs
  a case against it, freezes its requirement snapshot, and collects its
  evidence. It CLOSES a member only as that item's completion flow, or as
  another project's run carrying this project's source.

  A flow with no item-scoped stage is not a mistake: most delivery runs check
  nothing and close everything they carry. But a run that can do NEITHER
  gives the member nothing and is not free — membership is what holds the
  landing, so while this run is live or succeeded the next start on the
  item's completion flow will not enroll it. The add names that case, the
  flow that can close the item, and how to get there; it does not refuse.
"""


def deployment_runs_add_item(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs add-item",
        description=(
            "Attach one public item reference whose code the candidate does "
            "not carry but which the run should still deliver. Requires the "
            "caller's project deploy lock."
        ),
        epilog=CROSS_PROJECT_MEMBERSHIP_NOTE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("run_id")
    parser.add_argument("item")
    parser.add_argument("--project")
    parser.add_argument("--intent", choices=("progress", "final"), default=None)
    parser.add_argument("--requirement-id", type=int, action="append", default=[])
    parser.add_argument("--plan-id", type=int, action="append", default=[])
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ADD_ITEM_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        print((response.result or {}).get("message", ""), file=stdout)

    payload = {"run_id": parsed.run_id}
    if parsed.intent is not None:
        payload["delivery_intent"] = parsed.intent
    if parsed.requirement_id:
        payload["requirement_ids"] = parsed.requirement_id
    if parsed.plan_id:
        payload["plan_ids"] = parsed.plan_id
    return dispatch_and_emit(
        function_id="deployment_runs.add_item",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_validate_composition(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs validate-composition",
        description=(
            "Compose the run now from its candidate and report what "
            "enrolled or why it refused. Requires the caller's project "
            "deploy lock."
        ),
    )
    parser.add_argument("run_id")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, VALIDATE_COMPOSITION_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        print((response.result or {}).get("message", ""), file=stdout)

    return dispatch_and_emit(
        function_id="deployment_runs.validate_composition",
        target=TargetRef(
            kind="workflow_run",
            workflow_run_id=parsed.run_id,
        ),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "ADD_ITEM_USAGE",
    "VALIDATE_COMPOSITION_USAGE",
    "deployment_runs_add_item",
    "deployment_runs_validate_composition",
]
