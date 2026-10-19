"""Retrieve a typed review bundle for a full or terminated QA walk."""

import argparse
import json
import sys

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.public_ref import parse_public_item_ref
from yoke_core.api.service_client_structured_api_adapter import build_actor
from yoke_core.domain.qa_plan_execution import QaPlanExecutionError, _call_plan_function
from yoke_core.domain.qa_plan_execution_cli import _qualify_review_dispatch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa plan review-begin",
        description=__doc__,
        epilog="Retrieve the completed captures, then use the returned review-submit command. "
        "An aborted or errored execution remains terminal after their review. "
        "After restaffing, acquire the item work claim and use yoke qa plan adopt first.",
    )
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--item")
    subject.add_argument("--deployment-run-id")
    subject.add_argument("--project")
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--json", action="store_true")
    parsed = parser.parse_args(argv)
    if parsed.item:
        prefix, sequence = parse_public_item_ref(parsed.item)
        if prefix is None or sequence is None:
            print(
                "yoke qa plan review-begin: public_item_ref_required: pass --item PREFIX-N",
                file=sys.stderr,
            )
            return 2
        target = TargetRef(kind="item", public_ref=f"{prefix}-{sequence}")
    elif parsed.project:
        target = TargetRef(kind="global", project_id=parsed.project)
    else:
        target = TargetRef(
            kind="deployment_run", deployment_run_id=parsed.deployment_run_id
        )
    try:
        result = _call_plan_function(
            function_id="qa.plan_review.begin",
            target=target,
            payload={"execution_id": parsed.execution_id},
            actor=build_actor(session_id=parsed.session_id),
        )
        if result.get("review_bundle") is not None:
            _qualify_review_dispatch(result)
    except QaPlanExecutionError as exc:
        print(f"yoke qa plan review-begin: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
