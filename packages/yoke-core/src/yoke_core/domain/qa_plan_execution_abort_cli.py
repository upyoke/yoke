"""Explicit operator cleanup for an interrupted ordered QA plan execution."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.qa_plan_execution import QaPlanExecutionError, _call_plan_function


def run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke qa plan abort")
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--item")
    subject.add_argument("--deployment-run-id")
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--project")
    parser.add_argument("--session-id")
    parsed = parser.parse_args(args)

    from yoke_core.api.service_client_structured_api_adapter import build_actor

    target = (
        TargetRef(
            kind="item",
            item_ref=str(parsed.item),
            project_id=parsed.project,
        )
        if parsed.item
        else TargetRef(
            kind="deployment_run",
            deployment_run_id=str(parsed.deployment_run_id),
            project_id=parsed.project,
        )
    )
    try:
        result = _call_plan_function(
            function_id="qa.plan_execution.abort",
            target=target,
            payload={
                "execution_id": parsed.execution_id,
                "reason": parsed.reason,
            },
            actor=build_actor(session_id=parsed.session_id),
        )
    except QaPlanExecutionError as exc:
        print(f"yoke qa plan abort: {exc}", file=sys.stderr)
        return 2
    receipt = {
        key: result.get(key)
        for key in (
            "execution_id",
            "item_id",
            "deployment_run_id",
            "transition_id",
            "state",
            "cursor_ordinal",
            "machine_lease_id",
        )
    }
    print(json.dumps(receipt, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
