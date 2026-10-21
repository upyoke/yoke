"""Reviewer dispatch contracts for immutable QA capture bundles."""

from typing import Any, Mapping

from yoke_core.domain.dispatch_descriptors import DispatchDescriptor
from yoke_core.domain.qa_review_evidence import case_artifact_read_commands
from yoke_core.domain.qa_review_verdict_modes import (
    inconclusive_verdict_guidance,
    verdict_enum_text,
)


def _recorded_mission_clause(cases: list[Mapping[str, Any]], execution_id: str) -> str:
    """Teach the reviewer of a stopped execution how to judge its missions."""
    missions = [
        str(int(case["requirement_id"]))
        for case in cases
        if case.get("capture_runner") == "agent_mission"
    ]
    if not missions:
        return ""
    return (
        f" Execution {execution_id} stopped, so no walker can reach its Test "
        f"Machine: judge mission case(s) {', '.join(missions)} only from the "
        "mission evidence recorded before the stop. A docket that holds only "
        "setup and restore receipts carries no product proof."
    )


def dispatch_contract(
    bundle: Mapping[str, Any],
    *,
    allowed_verdicts: tuple[str, ...],
    conn: Any = None,
    missions_walkable: bool = True,
) -> dict[str, Any]:
    """Dispatch walkers for a live mission bundle; otherwise review the captures.

    A stopped execution has no host lease, so its recorded missions are judged
    from their captured evidence like every other case.
    """
    if missions_walkable and any(
        case.get("capture_runner") == "agent_mission" for case in bundle["cases"]
    ):
        from yoke_core.domain.agent_mission_review import (
            agent_mission_dispatch_contract,
        )

        return agent_mission_dispatch_contract(
            bundle, allowed_verdicts=allowed_verdicts, conn=conn
        )
    descriptor = DispatchDescriptor("tester")
    bundle_id = str(bundle["bundle_id"])
    digest = str(bundle["bundle_digest"])
    cases = bundle["cases"]
    subject = bundle["subject"]
    execution_target = bundle.get("execution_target")
    execution_target_digest = str(bundle.get("execution_target_digest") or "")
    environment = (
        execution_target.get("environment")
        if isinstance(execution_target, Mapping)
        else None
    )
    authority_bound = (
        isinstance(environment, Mapping)
        and bool(str(environment.get("name") or "").strip())
        and bool(execution_target_digest)
    )
    authority = {
        "state": "bound" if authority_bound else "unavailable",
        "environment": (
            str(environment.get("name") or "") if authority_bound else None
        ),
        "execution_target_digest": (
            execution_target_digest if authority_bound else None
        ),
    }
    from yoke_core.domain.qa_plan_review_subject import subject_flag

    subject_argument = subject_flag(subject, execution_target)
    artifact_read_commands = case_artifact_read_commands(cases)
    if authority_bound:
        prompt = (
            f"Review QA bundle {bundle_id} ({digest}) for immutable target "
            f"environment {authority['environment']} at target digest "
            f"{execution_target_digest}. Inspect every supplied transcript "
            "and visual artifact against that case's instructions and "
            "expected outcome. Return exactly one independent verdict and "
            f"rationale for each of the {len(cases)} cases. Do not infer a "
            "verdict from capture status. "
            + inconclusive_verdict_guidance(allowed_verdicts)
            + _recorded_mission_clause(cases, str(bundle["execution_id"]))
            + " Use only the "
            "supplied artifact-read commands for bytes that are not directly "
            "available — each lands the file and reports its path under the "
            "result path key, which is the only address you may open; "
            "artifact_handle.path names the capturing machine's disk. Refuse "
            "a missing or different target authority."
        )
        submit_command = (
            f"yoke qa plan review-submit {subject_argument} "
            f"--execution-id {bundle['execution_id']} --bundle-id {bundle_id} "
            f"--bundle-digest {digest} --stdin"
        )
    else:
        prompt = (
            f"QA bundle {bundle_id} ({digest}) predates immutable review "
            "authority binding and cannot be dispatched. Preserve it as "
            "historical evidence; do not query artifacts or submit verdicts."
        )
        submit_command = None
    return {
        "dispatch_kind": descriptor.dispatch_kind,
        "role": descriptor.role,
        "subagent_type": descriptor.subagent_type,
        "authority": authority,
        "artifact_read_commands": artifact_read_commands,
        "result_schema": {
            "verdicts": [
                {
                    "requirement_id": "integer",
                    "verdict": verdict_enum_text(allowed_verdicts),
                    "rationale": "non-empty string",
                }
            ]
        },
        "prompt": prompt,
        "submit_command": submit_command,
    }
