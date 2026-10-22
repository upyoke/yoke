"""Adopt an ended predecessor's QA execution without repeating captures."""

import argparse
import json
import sys

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.public_ref import parse_public_item_ref
from yoke_core.api.service_client_structured_api_adapter import build_actor
from yoke_core.domain.qa_plan_execution import QaPlanExecutionError, _call_plan_function


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa plan adopt",
        description=__doc__,
        epilog="Requires the item's current work claim and a verified ended predecessor. "
        "After adoption, review captured evidence with review-begin or resume the exact live execution.",
    )
    subject = parser.add_mutually_exclusive_group()
    subject.add_argument("--item")
    subject.add_argument("--project")
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--json", action="store_true")
    parsed = parser.parse_args(argv)
    if parsed.item:
        prefix, sequence = parse_public_item_ref(parsed.item)
        if prefix is None or sequence is None:
            print(
                "yoke qa plan adopt: public_item_ref_required: pass --item PREFIX-N",
                file=sys.stderr,
            )
            return 2
        target = TargetRef(kind="item", public_ref=f"{prefix}-{sequence}")
    else:
        target = TargetRef(kind="global", project_id=parsed.project)
    try:
        result = _call_plan_function(
            function_id="qa.plan_execution.adopt",
            target=target,
            payload={"execution_id": parsed.execution_id, "reason": parsed.reason},
            actor=build_actor(session_id=parsed.session_id),
        )
    except QaPlanExecutionError as exc:
        print(f"yoke qa plan adopt: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
