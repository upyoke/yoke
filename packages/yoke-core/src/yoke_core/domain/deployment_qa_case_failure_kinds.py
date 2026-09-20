"""What kind of unacceptable one blocking QA case is.

Four reasons a case is not acceptable, because they need four different
actions and used to read as one sentence. A determinate failing verdict
will never change by waiting; a case that never ran is waiting for a
runner; one whose verdict is ``undetermined`` is waiting for a judgment;
and a passing case whose evidence the gate cannot resolve is not waiting
for anything at all. Folding them together is what let a release sit for
hours reporting nothing while three of its cases had already failed.

The kinds describe the case. What a *stage* does with them is
:mod:`deployment_qa_stage_outcome`'s decision, and only a red case changes
it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


#: Latest verdict is a determinate failure. Nothing about waiting longer
#: changes it: the case must be re-run, corrected, or waived.
FAILURE_RED = "red"
#: No verdict has been recorded for this case at all.
FAILURE_UNRUN = "unrun"
#: A runner recorded a verdict it could not decide; a person owes one.
FAILURE_UNDETERMINED = "undetermined"
#: The case passed, but the gate resolved no attached evidence for it. The
#: owner sees a green case and the gate sees an unacceptable one, so this
#: is named rather than folded into "unrun" — nobody re-running the case
#: would learn why it is being held.
FAILURE_PASSED_WITHOUT_EVIDENCE = "passed_without_evidence"

#: Verdicts that settle a case negatively. ``undetermined`` is deliberately
#: absent: it is the runner declining to decide, not a decision.
RED_VERDICTS = frozenset({"fail", "error"})


@dataclass(frozen=True)
class CaseFailure:
    """One blocking case the stage cannot accept, and why."""

    requirement_id: int
    plan_case_key: str
    kind: str
    detail: str

    @property
    def red(self) -> bool:
        """True when a determinate failing verdict holds this case."""
        return self.kind == FAILURE_RED

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "plan_case_key": self.plan_case_key,
            "kind": self.kind,
            "detail": self.detail,
        }


def failure_reasons(failures: Sequence[CaseFailure]) -> list[str]:
    """The operator-readable sentence of each failure, in order."""
    return [failure.detail for failure in failures]


def red_failures(failures: Sequence[CaseFailure]) -> tuple[CaseFailure, ...]:
    """Only the cases a determinate failing verdict holds."""
    return tuple(failure for failure in failures if failure.red)


def classify_verdict(verdict: str) -> str:
    """Name what a case's latest verdict means for acceptance.

    ``pass`` never reaches here: a passing case is either acceptable or
    held by missing evidence, which is a separate read.
    """
    if verdict in RED_VERDICTS:
        return FAILURE_RED
    if verdict == "undetermined":
        return FAILURE_UNDETERMINED
    return FAILURE_UNRUN


__all__ = [
    "CaseFailure",
    "FAILURE_PASSED_WITHOUT_EVIDENCE",
    "FAILURE_RED",
    "FAILURE_UNDETERMINED",
    "FAILURE_UNRUN",
    "RED_VERDICTS",
    "classify_verdict",
    "failure_reasons",
    "red_failures",
]
