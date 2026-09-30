"""Human request policy for submitted QA plan-review verdicts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.qa_constants import UNDETERMINED_VERDICT
from yoke_core.domain.qa_review_verdict_modes import (
    allowed_review_verdicts,
    verdict_enum_text,
)
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.qa_plan_review import QaPlanReviewError


def ensure_plan_review_requests(
    conn: Any,
    *,
    bundle_id: str,
    verdicts: Mapping[int, tuple[str, str]],
    run_ids: Mapping[int, int],
    reviewer_actor_id: str | None,
    reviewer_session_id: str,
) -> dict[int, int]:
    """Create only the human work authorized by each case's stage policy."""
    p = marker(conn)
    requests: dict[int, int] = {}
    for requirement_id, (verdict, _rationale) in verdicts.items():
        if verdict != UNDETERMINED_VERDICT:
            continue
        from yoke_core.domain.qa_review_requests import (
            QA_REVIEW_DEFAULT_POLICY,
            ensure_qa_review_request,
        )

        row = conn.execute(
            f"SELECT deployment_run_id,deployment_stage,"
            f"deployment_member_item_id FROM qa_requirements WHERE id={p}",
            (int(requirement_id),),
        ).fetchone()
        policy = QA_REVIEW_DEFAULT_POLICY
        if row is not None:
            stage_name = row["deployment_stage"] if hasattr(row, "keys") else row[1]
            if stage_name is not None:
                deployment_run_id = (
                    row["deployment_run_id"] if hasattr(row, "keys") else row[0]
                )
                member = (
                    row["deployment_member_item_id"] if hasattr(row, "keys") else row[2]
                )
                from yoke_core.domain.approval_policy import parse_approval_policy
                from yoke_core.domain.deployment_qa_stage_contract import (
                    deployment_qa_stage_subject,
                )

                stage_subject = deployment_qa_stage_subject(
                    conn,
                    run_id=str(deployment_run_id),
                    stage_name=str(stage_name),
                    member_item_id=int(member) if member is not None else None,
                )
                verdict_policy = stage_subject["stage"]["verdict"]
                allowed = allowed_review_verdicts(verdict_policy.get("mode"))
                if UNDETERMINED_VERDICT not in allowed:
                    raise QaPlanReviewError(
                        f"deployment stage {stage_name!r} decides on the agent "
                        f"verdict alone, so it accepts only "
                        f"{verdict_enum_text(allowed)}; requirement "
                        f"{requirement_id} was submitted as "
                        f"{UNDETERMINED_VERDICT!r}. The dispatch contract for "
                        "this stage names the same set. Fail the case naming "
                        "the missing evidence in its rationale, or re-capture "
                        "and review again"
                    )
                policy = parse_approval_policy(
                    verdict_policy["reviewers"],
                    path="deployment stage verdict.reviewers",
                )

        from yoke_core.domain.qa_evidence_portability import EvidenceNotPortable

        try:
            request, _created = ensure_qa_review_request(
                conn,
                requirement_id=requirement_id,
                run_id=run_ids[requirement_id],
                policy=policy,
                originator_actor_id=(
                    int(reviewer_actor_id)
                    if reviewer_actor_id and str(reviewer_actor_id).isdigit()
                    else None
                ),
                session_id=reviewer_session_id,
                commit=False,
            )
        except EvidenceNotPortable as exc:
            raise QaPlanReviewError(str(exc)) from exc
        if request is None:
            continue
        request_id = int(request["id"])
        requests[requirement_id] = request_id
        conn.execute(
            "UPDATE qa_plan_review_verdicts SET decision_request_id="
            f"{p} WHERE bundle_id={p} AND requirement_id={p}",
            (request_id, bundle_id, requirement_id),
        )
    return requests


__all__ = ["ensure_plan_review_requests"]
