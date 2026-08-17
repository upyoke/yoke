"""Reviewer-only CLI for one complete QA plan verdict batch."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.qa_plan_execution import (
    QaPlanExecutionError,
    _call_plan_function,
)


def _verdicts(raw: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"stdin is not valid JSON: {exc}") from exc
    if isinstance(value, dict):
        value = value.get("verdicts")
    if not isinstance(value, list) or any(
        not isinstance(row, dict) for row in value
    ):
        raise ValueError(
            "stdin must be a verdict list or an object containing verdicts"
        )
    return value


def run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke qa plan review-submit")
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--item-id", type=int)
    subject.add_argument("--deployment-run-id")
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--bundle-digest", required=True)
    parser.add_argument("--stdin", action="store_true", required=True)
    parser.add_argument("--session-id")
    parsed = parser.parse_args(args)
    try:
        verdicts = _verdicts(sys.stdin.read())
    except ValueError as exc:
        print(f"yoke qa plan review-submit: {exc}", file=sys.stderr)
        return 2
    target = (
        TargetRef(kind="item", item_id=int(parsed.item_id))
        if parsed.item_id is not None
        else TargetRef(
            kind="deployment_run",
            deployment_run_id=str(parsed.deployment_run_id),
        )
    )
    from yoke_core.api.service_client_structured_api_adapter import build_actor

    try:
        result = _call_plan_function(
            function_id="qa.plan_review.submit",
            target=target,
            payload={
                "execution_id": parsed.execution_id,
                "bundle_id": parsed.bundle_id,
                "bundle_digest": parsed.bundle_digest,
                "verdicts": verdicts,
            },
            actor=build_actor(session_id=parsed.session_id),
        )
    except QaPlanExecutionError as exc:
        print(f"yoke qa plan review-submit: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    if result.get("submission") == "persisted":
        return 0
    return 1 if result.get("state") in {"failed", "needs_review"} else 0


def main(argv: Optional[List[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
