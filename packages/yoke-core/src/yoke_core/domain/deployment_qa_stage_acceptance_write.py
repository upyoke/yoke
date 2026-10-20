"""Write a passed deployment QA subject's stage acceptance under the run lock.

The gate reads everything first (:mod:`deployment_qa_stage_gate`); what is
left is the acceptance row, its verdict and any review request. The run row
lock covers only that, and every path commits, so no caller carries the lock
into its next member.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from yoke_core.domain.approval_policy import parse_approval_policy
from yoke_core.domain.deployment_qa_acceptance_record import (
    record_acceptance as _record_acceptance,
)
from yoke_core.domain.deployment_qa_stage_acceptance import (
    acceptance_waived,
    latest_verdict,
)
from yoke_core.domain.deployment_qa_stage_outcome import (
    OUTCOME_BLOCKED,
    OUTCOME_REJECTED,
    OUTCOME_WAITING,
    answer,
    passed,
)


@dataclass
class Acceptance:
    """A subject whose cases all passed; its acceptance is written under the lock."""

    subject: Mapping[str, Any]
    target: Mapping[str, Any]
    run_id: str
    execution: Mapping[str, Any]


@dataclass
class SharedParts:
    """A member answered by its shared groups and own subject, each read alike."""

    parts: list = field(default_factory=list)


def write_status(conn: Any, read: Any) -> dict[str, Any]:
    """Write each passed subject's acceptance under the run lock, then answer."""
    if isinstance(read, SharedParts):
        from yoke_core.domain.deployment_qa_shared_acceptance import combine_shared

        return combine_shared([write_status(conn, part) for part in read.parts])
    if not isinstance(read, Acceptance):
        return read
    subject, target, run_id, execution = (
        read.subject,
        read.target,
        read.run_id,
        read.execution,
    )
    from yoke_core.domain.deployment_qa_stage_gate import _acceptance_requirement

    # The run lock covers only the acceptance row and its verdict; every
    # path below commits, so no caller carries it into later members.
    conn.execute("SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE", (run_id,))
    requirement_id = _acceptance_requirement(conn, subject=subject, target=target)
    if acceptance_waived(conn, requirement_id):
        conn.commit()
        return passed()
    latest = latest_verdict(conn, requirement_id)
    if latest == "pass":
        conn.commit()
        return passed()
    if latest == "fail":
        conn.commit()
        return answer(
            accepted=False,
            outcome=OUTCOME_REJECTED,
            reasons=[f"stage acceptance requirement #{requirement_id} was rejected"],
        )
    verdict = subject["stage"]["verdict"]
    mode = str(verdict["mode"])
    if mode in {"agent_only", "human_if_unsure"}:
        _record_acceptance(
            conn,
            requirement_id=requirement_id,
            execution_id=str(execution["id"]),
            verdict="pass",
            reason=f"all scoped cases passed under {mode}",
        )
        conn.commit()
        return passed()
    # The undetermined acceptance and its review request stand or fall
    # together: no review is requested against evidence a reviewer cannot
    # open, and a repaired stage re-evaluates from the same state.
    conn.execute("SAVEPOINT stage_acceptance_review")
    if latest != "undetermined":
        review_run_id = _record_acceptance(
            conn,
            requirement_id=requirement_id,
            execution_id=str(execution["id"]),
            verdict="undetermined",
            reason="configured deployment stage requires authorized human acceptance",
        )
    else:
        from yoke_core.domain.qa_latest_execution import latest_executions

        review_run_id = int(
            latest_executions(conn, [requirement_id])[requirement_id]["id"]
        )
    from yoke_core.domain.qa_evidence_portability import EvidenceNotPortable
    from yoke_core.domain.qa_review_requests import ensure_qa_review_request

    try:
        request, _created = ensure_qa_review_request(
            conn,
            requirement_id=requirement_id,
            run_id=review_run_id,
            policy=parse_approval_policy(
                verdict["reviewers"], path="deployment stage verdict.reviewers"
            ),
            commit=False,
        )
    except EvidenceNotPortable as exc:
        conn.execute("ROLLBACK TO SAVEPOINT stage_acceptance_review")
        conn.commit()
        return answer(accepted=False, outcome=OUTCOME_BLOCKED, reasons=[str(exc)])
    conn.commit()
    request_id = int(request["id"]) if request is not None else None
    return answer(
        accepted=False,
        outcome=OUTCOME_WAITING,
        reasons=[
            f"stage acceptance requirement #{requirement_id} awaits authorized human review"
        ],
        request_id=request_id,
    )


__all__ = ["Acceptance", "SharedParts", "write_status"]
