"""Read the partitions for one QA subject."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.qa_plan_execution_dispatch import call_plan_function
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.qa_plan_execution_target import build_plan_execution_target


def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa plan partitions", description="Read QA partitions and their custody."
    )
    parser.add_argument("--item", help="Item whose attached QA partitions to read.")
    parser.add_argument("--transition", help="Workflow transition of the attached item plans.")
    parser.add_argument("--stage", help="Deployment stage whose QA partitions to read.")
    parser.add_argument("--deployment-run-id", help="Deployment run that owns the stage QA.")
    parser.add_argument("--plan", help="Plan to read for a standalone or deployment subject.")
    parser.add_argument("--project", help="Project that owns the plan.")
    parser.add_argument("--checkout-path", help="Checkout path used to resolve the source lane.")
    parser.add_argument("--expected-branch", help="Branch the source checkout must be on.")
    parser.add_argument("--expected-sha", help="Expected source commit for this read.")
    parser.add_argument("--session-id", help="Override the detected caller session.")
    parser.add_argument("--json", action="store_true", help="Emit the JSON result.")
    parsed = parser.parse_args(args)
    if parsed.deployment_run_id and not parsed.stage:
        parser.error("--deployment-run-id requires --stage")
    if parsed.deployment_run_id and not (parsed.item or parsed.plan):
        parser.error("a run-wide read requires --plan")
    from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch
    from yoke_core.domain.qa_case_execution import QaCaseExecutionError

    actor = get_structured_dispatch().build_actor(session_id=parsed.session_id)
    try:
        target, payload = build_plan_execution_target(
            public_ref=parsed.item, transition_id=parsed.transition,
            deployment_run_id=parsed.deployment_run_id, deployment_stage=parsed.stage,
            deployment_member=None, plan=parsed.plan, project=parsed.project,
        )
        checkout = str(Path(parsed.checkout_path).resolve()) if parsed.checkout_path else None
        if parsed.item and parsed.transition:
            from yoke_core.domain.qa_lane_head import reconcile_plan_lanes

            reconcile_plan_lanes(
                target, transition_id=parsed.transition, requirement_id=None,
                checkout_path=checkout, expected_branch=parsed.expected_branch,
                actor=actor, call=call_plan_function,
            )
        result = call_plan_function(
            function_id="qa.plan_execution.partitions",
            target=target,
            payload={
                **payload,
                "checkout_path": checkout,
                "expected_branch": parsed.expected_branch,
                "source_revision": parsed.expected_sha,
            },
            actor=actor,
        )
    except (QaPlanExecutionError, QaCaseExecutionError) as exc:
        print(f"yoke qa plan partitions: {exc}", file=sys.stderr)
        return 2
    if parsed.json:
        print(dumps_compact(result))
    else:
        _print_partitions(result)
    return 0


def _print_partitions(result: dict) -> None:
    if lane := result.get("lane"):
        print(f"Lane {lane.get('lane_path') or 'unavailable'}")
        if lane.get("lane_branch"):
            print(f"  Branch {lane['lane_branch']} at {lane.get('lane_commit_sha') or 'unrecorded'}")
    for row in result["partitions"]:
        cases = ", ".join(case["case_key"] for case in row["cases"])
        hosts = ", ".join(row["hosts"]) or "none selected"
        print(f"{row['key']}  {row['state']}  {row['kind']}  hosts {hosts}  cases {cases}")
        if row.get("execution_id"):
            print(f"  Held by execution {row['execution_id']} in session {row['session_id']}")
        if row["blocked_by"]:
            print(f"  Waiting for partitions {', '.join(row['blocked_by'])}")
    if not result["partitions"]:
        print("No QA partitions for the selected subject.")


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
