"""Attach exact-candidate consumer CI evidence to the producer item."""

from __future__ import annotations

import json

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.public_item_target import public_item_target


def requirement(read, public_ref: str, consumer: str, transition: str) -> int:
    target = public_item_target(public_ref)
    suite = f"consumer-proof:{consumer}"
    rows = read("qa.requirement.list", {}, target=target).get("rows", [])
    matches = [
        row
        for row in rows
        if row.get("suite_id") == suite
        and row.get("requirement_source") == "flow_derived"
        and not row.get("retracted_at")
        and not row.get("waived_at")
    ]
    if len(matches) > 1:
        raise RuntimeError(
            f"consumer_proof_requirement_ambiguous: {suite}; reconcile duplicate requirements and retry merge"
        )
    if matches:
        if matches[0].get("blocking_mode") == "non_blocking":
            read(
                "qa.requirement.update",
                {"field": "blocking_mode", "value": "blocking"},
                target=TargetRef(
                    kind="qa_requirement", qa_requirement_id=int(matches[0]["id"])
                ),
            )
        return int(matches[0]["id"])
    return int(
        read(
            "qa.requirement.add",
            {
                "qa_kind": "ac_verification",
                "qa_phase": "verification",
                "blocking_mode": "blocking",
                "requirement_source": "flow_derived",
                "suite_id": suite,
                "workflow_transition_id": transition,
                "instructions": f"Build consumer {consumer} against the exact published producer candidate",
                "expected_outcome": "The declared consumer workflow succeeds on the bound pair",
            },
            target=target,
        )["requirement_id"]
    )


def reconcile(read, public_ref: str, consumers: set[str]) -> None:
    """Keep historical evidence without gating a contract this candidate no longer changes."""
    rows = read("qa.requirement.list", {}, target=public_item_target(public_ref)).get(
        "rows", []
    )
    for row in rows:
        suite = str(row.get("suite_id") or "")
        if (
            row.get("requirement_source") == "flow_derived"
            and suite.startswith("consumer-proof:")
            and suite.removeprefix("consumer-proof:") not in consumers
            and not row.get("retracted_at")
            and not row.get("waived_at")
            and row.get("blocking_mode") == "blocking"
        ):
            read(
                "qa.requirement.update",
                {"field": "blocking_mode", "value": "non_blocking"},
                target=TargetRef(
                    kind="qa_requirement", qa_requirement_id=int(row["id"])
                ),
            )


def record(
    read,
    requirement_id: int,
    *,
    candidate: str,
    consumer: str,
    consumer_sha: str,
    run: dict,
    inputs: dict,
    workflow: str,
    refusal: str,
) -> None:
    read(
        "qa.run.add",
        {
            "performed_by": "agent",
            "qa_kind": "ac_verification",
            "verdict": "fail" if refusal else "pass",
            "head_sha": candidate,
            "raw_result": json.dumps(
                {
                    "verification_tree": {"head_sha": candidate},
                    "consumer_project": consumer,
                    "consumer_sha": consumer_sha,
                    "workflow": workflow,
                    "inputs": inputs,
                    "consumer_run": run,
                    "refusal": refusal,
                },
                sort_keys=True,
            ),
        },
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
    )
