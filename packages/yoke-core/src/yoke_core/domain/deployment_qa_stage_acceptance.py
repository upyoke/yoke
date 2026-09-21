"""Read whether one pinned deployment QA stage subject is already accepted.

:mod:`deployment_qa_stage_gate` answers the same question while the
pipeline is standing on the stage, and *settles* it: it materializes the
acceptance requirement, records an agent verdict when the stage's mode
allows one, and opens the human review request when it does not. A
later reader -- the release-to-done gate, which runs long after the run
left the stage -- must not do any of that: it needs the answer as it
already stands, with no write and no assumption that the stage is the
run's active one.

Both directions share these readers so "accepted" means one thing in
both places. Nothing here writes, and nothing here requires the stage to
be active.
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
from yoke_core.domain.refusal_recovery import compose_refusal


def latest_verdict(conn: Any, requirement_id: int) -> str:
    """The newest recorded verdict for one requirement (``""`` when none)."""
    row = conn.execute(
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (int(requirement_id),),
    ).fetchone()
    if row is None:
        return ""
    return str(row["verdict"] if hasattr(row, "keys") else row[0] or "")


def acceptance_waived(conn: Any, requirement_id: int) -> bool:
    """True when an authorized waiver already discharged this requirement."""
    row = conn.execute(
        "SELECT waived_at FROM qa_requirements WHERE id=%s", (int(requirement_id),)
    ).fetchone()
    if row is None:
        return False
    return bool(row["waived_at"] if hasattr(row, "keys") else row[0])


def completed_execution(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> dict[str, Any] | None:
    """The newest completed execution recorded against this exact target.

    The digest predicate is the target-identity check: an execution
    recorded against a replaced target simply is not selected, so a
    superseded producer receipt can never answer for the current one.
    """
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    row = conn.execute(
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
        "AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s "
        "AND execution_target_digest=%s AND state='completed' "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (run_id, stage_name, member_item_id or 0, execution_target_digest),
    ).fetchone()
    if row is None:
        return None
    execution_id = row["id"] if hasattr(row, "keys") else row[0]
    return select_plan_execution(conn, str(execution_id), lock=False)


def existing_acceptance_requirement(
    conn: Any,
    *,
    subject: Mapping[str, Any],
    target: Mapping[str, Any],
    acceptance_qa_kind: str,
) -> int | None:
    """This subject's acceptance requirement for the target, if it exists.

    ``None`` means no acceptance requirement has been materialized for
    this exact target yet. A stage whose target was replaced keeps its
    older requirement rows untouched and unmatched -- the replacement
    target gets its own row rather than inheriting the earlier verdict.
    """
    run_id = str(subject["id"])
    stage_name = str(subject["stage"]["name"])
    member = subject.get("member_item_id")
    rows = conn.execute(
        "SELECT id,execution_target_json,execution_target_digest "
        "FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s AND qa_kind=%s "
        "ORDER BY id",
        (run_id, stage_name, member or 0, acceptance_qa_kind),
    ).fetchall()
    expected_json = target_authority.canonical_target(target)
    expected_digest = target_authority.target_digest(target)
    matches = [
        row
        for row in rows
        if str(row["execution_target_json"] or "") == expected_json
        and str(row["execution_target_digest"] or "") == expected_digest
    ]
    if len(matches) > 1:
        raise ValueError(
            "deployment stage acceptance was materialized more than once; "
            "resolve the duplicate before resuming the pipeline"
        )
    if not matches:
        return None
    row = matches[0]
    return int(row["id"] if hasattr(row, "keys") else row[0])


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


@dataclass(frozen=True)
class StageAcceptance:
    """One stage subject's acceptance, as a state and the reasons behind it."""

    state: str
    blockers: tuple[str, ...]

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
    failures = failure_reasons(
        case_failures(
            conn,
            run_id=run_id,
            stage_name=stage_name,
            member_item_id=member_item_id,
            execution_target_digest=digest,
        )
    )
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
            # fully-waived member unreleasable without removing it from the
            # run, which deployment membership has no way to do.
            return StageAcceptance(STAGE_DISCHARGED, ())
        return StageAcceptance(
            STAGE_NOT_RUN,
            ("no completed scoped QA execution exists", *failures),
        )
    if failures:
        return StageAcceptance(STAGE_CASES_UNRESOLVED, tuple(failures))
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
    "stage_acceptance",
    "stage_acceptance_blockers",
    "unsettled_acceptance_blocker",
]
