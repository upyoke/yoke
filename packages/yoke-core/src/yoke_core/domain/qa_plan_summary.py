"""The QA plan shape a reader gets before asking for the probe itself.

Most reads of a plan answer "what does this plan cover, and where does it
stand": the cases, the method behind each, the environment they run
against, and each case's latest verdict. The plan document also carries
what a probe actually *does* — its instructions, expected outcome and
method config — plus, for every proof, the captured output tail, the
evidence artifacts and the review record. Those are the bulk of the
document and are read deliberately, not while scanning.

So the default is this projection and the whole document is served on
``detail="full"``. Nothing is summarized away silently: the summary names
the command that returns the rest.

The projection runs over an already-built plan, so an outcome shown here
is the same value the full document would show, computed once.
"""

from __future__ import annotations

from typing import Any

#: Case fields a reader scanning a plan needs.
_CASE_FIELDS = (
    "id",
    "case_key",
    "position",
    "method_id",
    "method_name",
    "runner_id",
    "required_capability_kinds",
    "host_baselines",
    "entry_surface",
    "required_completion",
)

#: Proof fields that carry a verdict rather than the evidence behind it.
_PROOF_FIELDS = (
    "requirement_id",
    "run_id",
    "deployment_run_id",
    "host_baseline",
    "outcome",
    "happened_at",
)


def _proof(proof: dict[str, Any]) -> dict[str, Any]:
    return {key: proof[key] for key in _PROOF_FIELDS if key in proof}


def _case(case: dict[str, Any]) -> dict[str, Any]:
    summary = {key: case[key] for key in _CASE_FIELDS if key in case}
    summary["proofs"] = [_proof(proof) for proof in case.get("proofs") or []]
    if "last_result" in case:
        summary["last_result"] = _proof(case["last_result"])
    return summary


def plan_summary(plan: dict[str, Any], *, project: str) -> dict[str, Any]:
    """Project one full plan document down to its scannable summary."""
    summary = {
        key: value
        for key, value in plan.items()
        if key not in {"cases", "attachments"}
    }
    summary["cases"] = [_case(case) for case in plan.get("cases") or []]
    summary["attachment_count"] = len(plan.get("attachments") or [])
    summary["detail_read"] = (
        f"yoke qa plan get {plan['id']} --project {project} --full"
    )
    return summary


__all__ = ["plan_summary"]
