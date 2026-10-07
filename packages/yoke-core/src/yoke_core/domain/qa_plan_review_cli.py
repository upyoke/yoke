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
from yoke_core.domain.qa_review_verdict_modes import (
    ALL_REVIEW_VERDICTS,
    verdict_enum_text,
)


def _submission(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"stdin is not valid JSON: {exc}") from exc
    if isinstance(value, dict) and "host_wait" in value:
        if set(value) != {"host_wait"}:
            raise ValueError("host_wait is submitted alone, without verdicts")
        return value
    if isinstance(value, dict):
        value = value.get("verdicts")
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(
            "stdin must be a verdict list or an object containing verdicts"
        )
    return {"verdicts": value}


def _help_epilogue() -> str:
    """The stdin contract, so it is readable before a batch is composed.

    A reviewer discovering the schema from a rejection has already spent the
    review. The verdict set a *given* stage accepts is narrower than this
    superset and is named by that bundle's own dispatch contract, which is
    the authority; ``agent_only`` stages accept only the conclusive two.
    """
    return (
        "stdin: one complete batch, either a verdict list or an object with a\n"
        '  "verdicts" key. Every bundle case needs exactly one row:\n'
        "\n"
        '    {"verdicts": [\n'
        '      {"requirement_id": 123, "verdict": "pass", '
        '"rationale": "what the evidence showed"}\n'
        "    ]}\n"
        "\n"
        f"  requirement_id  integer, a case in this bundle\n"
        f"  verdict         {verdict_enum_text(ALL_REVIEW_VERDICTS)} "
        "(this stage may accept fewer --\n"
        "                  read dispatch.result_schema on the bundle)\n"
        "  rationale       non-empty string; for an inconclusive verdict, what\n"
        "                  could not be established and why\n"
        "\n"
        "A partial batch is refused: the bundle settles as one submission.\n"
        "Host contention is a hold, never a verdict (including agent_only).\n"
        'Submit {"host_wait":{"machine":"NAME","rationale":"holder evidence"}}\n'
        "alone to keep requirements open and queue a fresh mission in FIFO order."
    )


def _unfinished_walk(
    target: TargetRef,
    actor: Any,
    *,
    execution_id: str,
    requirement_id: Any,
) -> str | None:
    """Name a mission whose walk left the Test Machine unrestored.

    The verdict makes the execution terminal and releases the lease, after
    which nothing may touch the host for it, so the walk's own ``walk-end``
    must have removed its scratch and restored its starting state first. A
    case with no live mission lease has nothing here.
    """
    if not isinstance(requirement_id, int):
        return None
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    access = call_qa_function(
        function_id="test_machine.mission.access",
        target=target,
        payload={"execution_id": execution_id, "requirement_id": requirement_id},
        actor=actor,
    )
    contract = (access.result or {}).get("execution") if access.success else None
    if not isinstance(contract, dict):
        return None
    try:
        from yoke_core.domain.machine_qa_host_control import (
            register_test_machine_host_control,
        )
        from yoke_core.domain.machine_qa_mission_walk import mission_walk_unfinished

        register_test_machine_host_control()
        unfinished = mission_walk_unfinished(contract)
    except Exception as exc:
        return f"requirement {requirement_id}: host probe failed ({exc})"
    if not unfinished:
        return None
    return (
        f"requirement {requirement_id}: its walk never ran `yoke qa mission "
        f"walk-end ... --execution-id {execution_id} --requirement-id "
        f"{requirement_id} --run-id RUN`, so its scratch is still on the Test "
        "Machine and its starting state was not restored; run that command "
        "(the dispatch contract names the run id) and submit again"
    )


def run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa plan review-submit",
        description=__doc__,
        epilog=_help_epilogue(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--item-id", type=int)
    subject.add_argument("--deployment-run-id")
    subject.add_argument("--project")
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--bundle-digest", required=True)
    parser.add_argument("--stdin", action="store_true", required=True)
    parser.add_argument("--session-id")
    parsed = parser.parse_args(args)
    try:
        submission = _submission(sys.stdin.read())
    except ValueError as exc:
        print(f"yoke qa plan review-submit: {exc}", file=sys.stderr)
        return 2
    target = (
        TargetRef(kind="item", item_id=int(parsed.item_id))
        if parsed.item_id is not None
        else TargetRef(kind="global", project_id=parsed.project)
        if parsed.project
        else TargetRef(
            kind="deployment_run",
            deployment_run_id=str(parsed.deployment_run_id),
        )
    )
    from yoke_core.api.service_client_structured_api_adapter import build_actor

    actor = build_actor(session_id=parsed.session_id)
    unfinished = [
        reason
        for verdict in submission.get("verdicts") or ()
        if (
            reason := _unfinished_walk(
                target,
                actor,
                execution_id=parsed.execution_id,
                requirement_id=verdict.get("requirement_id"),
            )
        )
    ]
    if unfinished:
        for reason in unfinished:
            print(
                f"yoke qa plan review-submit: mission_walk_unfinished: {reason}",
                file=sys.stderr,
            )
        return 2
    try:
        result = _call_plan_function(
            function_id="qa.plan_review.submit",
            target=target,
            payload={
                "execution_id": parsed.execution_id,
                "bundle_id": parsed.bundle_id,
                "bundle_digest": parsed.bundle_digest,
                **submission,
            },
            actor=actor,
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
