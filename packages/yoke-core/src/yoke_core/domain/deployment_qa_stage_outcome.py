"""What one deployment QA stage subject's acceptance boundary answered.

Five answers, because five different things are true of a stage and each
one asks a different thing of the operator. Two accept it: ``passed``,
and ``discharged`` for a subject whose every case was waived or superseded
so there was nothing left to run. Three do not: ``waiting`` means something
has yet to happen, ``rejected`` means an authorized reviewer turned the
stage's own acceptance requirement down, and ``blocked`` means a scoped
case holds a determinate failing verdict.

``blocked`` exists because ``waiting`` used to cover it. A case whose
latest verdict was ``fail`` and a case that had never run produced the
same answer, so "this run cannot finish as it stands" was not a state the
system could be in, and a release with three red requirements reported
nothing for four hours before a person cancelled it.

Splitting them changes what the operator is told and nothing about what
makes a stage acceptable: ``blocked`` carries ``accepted=False`` exactly
as ``waiting`` did.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_qa_case_failure_kinds import (
    CaseFailure,
    red_failures,
)


#: A stage subject's settled answer, named where it is decided so callers
#: do not re-derive it by reading the reason strings.
OUTCOME_PASSED = "passed"
OUTCOME_REJECTED = "rejected"
OUTCOME_WAITING = "waiting"
#: Nothing was left to execute: every case was waived or superseded, or the
#: member recorded before its deploy that it needs no post-deploy check at
#: all. Accepted for gating, named separately so a discharge never reads
#: back as a result that passed.
OUTCOME_DISCHARGED = "discharged"
#: At least one scoped case holds a determinate failing verdict, so this
#: stage cannot finish as it stands. Not acceptable -- exactly as unacceptable
#: as waiting was -- but a different answer to a different question: waiting
#: says "something has yet to happen", blocked says "what happened was a
#: failure, and no amount of waiting will change it".
OUTCOME_BLOCKED = "blocked"


def answer(
    *,
    accepted: bool,
    outcome: str,
    reasons: list[str],
    failures: tuple[CaseFailure, ...] = (),
    request_id: int | None = None,
) -> dict[str, Any]:
    """One shape for every answer, so a reader never probes for a key.

    ``case_failures`` rides on every outcome, empty where there are none.
    A caller that needs to tell a red case from an unrun one, or to name
    the requirement behind a passing case with unreadable evidence, reads
    it rather than matching on the reason sentences.
    """
    return {
        "accepted": accepted,
        "outcome": outcome,
        "reasons": reasons,
        "case_failures": [failure.to_dict() for failure in failures],
        "request_id": request_id,
    }


def waiting(
    reasons: list[str], failures: tuple[CaseFailure, ...] = ()
) -> dict[str, Any]:
    return answer(
        accepted=False,
        outcome=OUTCOME_WAITING,
        reasons=reasons,
        failures=failures,
    )


def _blocked(reasons: list[str], failures: tuple[CaseFailure, ...]) -> dict[str, Any]:
    """A stage held by determinate failures, named with its recovery."""
    red = red_failures(failures)
    named = ", ".join(f"#{failure.requirement_id}" for failure in red)
    return answer(
        accepted=False,
        outcome=OUTCOME_BLOCKED,
        reasons=[
            *reasons,
            f"this stage cannot finish as it stands: {len(red)} scoped case(s) "
            f"hold a determinate failing verdict ({named}).",
            "Settle or waive each one through its registered QA surface, then "
            "re-drive the run.",
        ],
        failures=failures,
    )


def settled(reasons: list[str], failures: tuple[CaseFailure, ...]) -> dict[str, Any]:
    """Waiting, or blocked when a determinate failure is among the reasons."""
    if red_failures(failures):
        return _blocked(reasons, failures)
    return waiting(reasons, failures)


def passed() -> dict[str, Any]:
    return answer(accepted=True, outcome=OUTCOME_PASSED, reasons=[])


def discharged() -> dict[str, Any]:
    return answer(accepted=True, outcome=OUTCOME_DISCHARGED, reasons=[])


__all__ = [
    "OUTCOME_BLOCKED",
    "OUTCOME_DISCHARGED",
    "OUTCOME_PASSED",
    "OUTCOME_REJECTED",
    "OUTCOME_WAITING",
    "answer",
    "discharged",
    "passed",
    "settled",
    "waiting",
]
