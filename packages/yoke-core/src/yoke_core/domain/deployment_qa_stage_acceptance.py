"""Read a pinned deployment QA subject's existing acceptance without writes.

The active stage gate and later release readers share this authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yoke_core.domain.deployment_qa_case_failure_kinds import failure_reasons
from yoke_core.domain.deployment_qa_stage_case_failures import (
    case_failures,
    obligations_fully_discharged,
)
from yoke_core.domain.deployment_qa_admission_materialization import (
    fulfill_admitted_obligations,
)
from yoke_core.domain import qa_execution_environment_target as target_authority
from yoke_core.domain.post_deploy_verification_answer import member_post_deploy_answer
from yoke_core.domain.qa_pending_agent_review import (
    pending_review_for_stage,
    stage_review_pending_blocker,
)
from yoke_core.domain.refusal_recovery import compose_refusal
from yoke_core.domain.deployment_qa_acceptance_reads import (
    acceptance_waived,
    completed_execution,
    existing_acceptance_requirement,
)


def latest_verdict(conn: Any, requirement_id: int) -> str:
    """The newest recorded verdict for one requirement (``""`` when none)."""
    from yoke_core.domain.qa_latest_execution import latest_verdict_executions

    row = latest_verdict_executions(conn, [requirement_id]).get(int(requirement_id))
    if row is None:
        return ""
    return str(row["verdict"] or "")


#: What one stage subject's acceptance currently is, in one word. Closed
#: because surfaces render it directly: a card has room for a state, not for
#: the sentence that explains it.
STAGE_ACCEPTED = "accepted"
STAGE_NOT_RUN = "not yet run"
#: Every reason the case rung can give — a case that failed, one still
#: undetermined, one missing its evidence — shares this state, because
#: the rung reports sentences rather than verdicts and calling an
#: undetermined case "failed" would assert a verdict nobody recorded.
STAGE_CASES_UNRESOLVED = "cases unresolved"
STAGE_INCOMPLETE = "incomplete"
STAGE_UNSETTLED = "not settled"
#: Every case was waived or superseded, so nothing remained to execute. It
#: gates exactly like ``accepted`` and reads differently on purpose: the
#: release contract keeps an authorized discharge distinguishable from a
#: result something actually passed.
STAGE_DISCHARGED = "discharged"
STAGE_REJECTED = "rejected"
STAGE_AWAITING_REVIEW = "awaiting review"


def unsettled_acceptance_blocker(*, execution_id: object, digest: str) -> str:
    """Whole-state recovery for an unmatched completed execution."""
    return compose_refusal(
        "stage acceptance was never settled against this deployment target",
        evaluated=(
            f"completed scoped execution {execution_id} matches digest "
            f"{digest}; no case failed"
        ),
        recovery=(
            "re-drive the deployment run; steering owns the run and there "
            "is no member or worker action"
        ),
    )


def missing_execution_blocker(
    conn: Any,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> tuple[str, str]:
    """Why a subject has no completed execution: review pending, or never run."""
    pending = pending_review_for_stage(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_target_digest=execution_target_digest,
    )
    if pending is not None:
        return STAGE_AWAITING_REVIEW, stage_review_pending_blocker(pending)
    return STAGE_NOT_RUN, "no completed scoped QA execution exists"


@dataclass(frozen=True)
class StageAcceptance:
    """One stage subject's acceptance, as a state and the reasons behind it."""

    state: str
    blockers: tuple[str, ...]
    failed_requirement_ids: tuple[int, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.state in (STAGE_ACCEPTED, STAGE_DISCHARGED)


def stage_acceptance(
    conn: Any,
    *,
    subject: Mapping[str, Any],
    target: Mapping[str, Any],
    acceptance_qa_kind: str,
) -> StageAcceptance:
    """Where this stage subject stands, read without settling anything.

    The same ladder :mod:`deployment_qa_stage_gate` settles, read as it
    already stands: concrete case evidence, then the admitted aggregate
    obligations, then the acceptance requirement's own verdict. An acceptance
    requirement that was never materialized blocks -- the reader never
    creates one, because creating it is the active stage's job and a missing
    one means the stage was never settled at all.

    One walk answers both shapes a caller needs. A gate wants the sentences,
    a card wants the word, and deriving either from the other -- by matching
    on blocker text, or by walking the ladder twice -- is how the two
    surfaces start disagreeing about what "accepted" means.
    """
    from yoke_core.domain.deployment_qa_shared_acceptance import (
        shared_member_acceptance,
    )

    shared = shared_member_acceptance(conn, subject, target, acceptance_qa_kind)
    if shared is not None:
        return shared
    run_id = str(subject["id"])
    stage_name = str(subject["stage"]["name"])
    member_item_id = subject.get("member_item_id")
    digest = target_authority.target_digest(target)
    execution = completed_execution(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_target_digest=digest,
    )
    cases = case_failures(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_target_digest=digest,
        shared_plan_id=(subject.get("shared_plan") or {}).get("plan_id"),
    )
    failures = failure_reasons(cases)
    red_ids = tuple(case.requirement_id for case in cases if case.red)
    if execution is None:
        if obligations_fully_discharged(
            conn,
            run_id=run_id,
            stage_name=stage_name,
            member_item_id=member_item_id,
            execution_target_digest=digest,
        ):
            # Waiving or superseding every case leaves no case to run, so
            # demanding a scoped execution here would block on evidence the
            # discharge already stood in for -- the trap that made a
            # fully-waived member unreleasable until its discharge was read.
            return StageAcceptance(STAGE_DISCHARGED, ())
        if member_post_deploy_answer(conn, subject).discharges_without_cases:
            return StageAcceptance(STAGE_DISCHARGED, ())
        state, reason = missing_execution_blocker(
            conn, run_id, stage_name, member_item_id, digest
        )
        return StageAcceptance(state, (reason, *failures), red_ids)
    if failures:
        return StageAcceptance(STAGE_CASES_UNRESOLVED, tuple(failures), red_ids)
    obligation_failures = fulfill_admitted_obligations(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_id=str(execution["id"]),
        execution_target_digest=digest,
        acceptance_qa_kind=acceptance_qa_kind,
    )
    if obligation_failures:
        return StageAcceptance(STAGE_INCOMPLETE, tuple(obligation_failures))
    requirement_id = existing_acceptance_requirement(
        conn,
        subject=subject,
        target=target,
        acceptance_qa_kind=acceptance_qa_kind,
    )
    if requirement_id is None:
        return StageAcceptance(
            STAGE_UNSETTLED,
            (
                unsettled_acceptance_blocker(
                    execution_id=execution["id"], digest=digest
                ),
            ),
        )
    if acceptance_waived(conn, requirement_id):
        return StageAcceptance(STAGE_ACCEPTED, ())
    latest = latest_verdict(conn, requirement_id)
    if latest == "pass":
        return StageAcceptance(STAGE_ACCEPTED, ())
    if latest == "fail":
        return StageAcceptance(
            STAGE_REJECTED,
            (f"stage acceptance requirement #{requirement_id} was rejected",),
            (requirement_id,),
        )
    return StageAcceptance(
        STAGE_AWAITING_REVIEW,
        (
            f"stage acceptance requirement #{requirement_id} awaits authorized "
            "human review",
        ),
    )


def stage_acceptance_blockers(
    conn: Any,
    *,
    subject: Mapping[str, Any],
    target: Mapping[str, Any],
    acceptance_qa_kind: str,
) -> list[str]:
    """Every reason this stage subject is not yet accepted (``[]`` = accepted)."""
    return list(
        stage_acceptance(
            conn,
            subject=subject,
            target=target,
            acceptance_qa_kind=acceptance_qa_kind,
        ).blockers
    )


__all__ = [
    "STAGE_ACCEPTED",
    "STAGE_AWAITING_REVIEW",
    "STAGE_DISCHARGED",
    "STAGE_CASES_UNRESOLVED",
    "STAGE_INCOMPLETE",
    "STAGE_NOT_RUN",
    "STAGE_REJECTED",
    "STAGE_UNSETTLED",
    "StageAcceptance",
    "acceptance_waived",
    "completed_execution",
    "existing_acceptance_requirement",
    "latest_verdict",
    "missing_execution_blocker",
    "stage_acceptance",
    "stage_acceptance_blockers",
    "unsettled_acceptance_blocker",
]
