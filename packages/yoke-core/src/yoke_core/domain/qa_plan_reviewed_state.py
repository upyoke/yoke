"""Fold a submitted review batch into an execution's durable case results.

Deterministic results keep their recorded outcomes: a reviewer verdicts only
the bundle's cases, so a case that failed or was blocked before the review
still settles the execution as failed and is named in its release reason.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain.qa_constants import case_outcome_for_verdict
from yoke_core.domain.qa_plan_execution_abort_reason import case_failed_reason
from yoke_core.domain.qa_plan_execution_result_state import (
    aggregate_state,
    case_failed,
)

#: Release reason of a reviewed execution in which every case settled clean.
REVIEW_COMPLETE_REASON = "qa-plan-agent-review-complete"


def _reviewed_results(
    recorded_results: Sequence[Mapping[str, Any]],
    reviewed_verdicts: Mapping[int, tuple[str, str]],
) -> list[dict[str, Any]]:
    from yoke_core.domain.qa_plan_review import QaPlanReviewError

    folded: list[dict[str, Any]] = []
    seen_reviewed: set[int] = set()
    for row in recorded_results:
        requirement_id = int(row.get("requirement_id") or 0)
        raw_result = row.get("result")
        if requirement_id < 1 or not isinstance(raw_result, Mapping):
            raise QaPlanReviewError(
                "QA execution contains an invalid durable case result"
            )
        result = {**raw_result, "requirement_id": requirement_id}
        if requirement_id in reviewed_verdicts:
            verdict = reviewed_verdicts[requirement_id][0]
            result["verdict"] = verdict
            result["case_outcome"] = case_outcome_for_verdict(verdict)
            seen_reviewed.add(requirement_id)
        folded.append(result)
    if seen_reviewed != set(reviewed_verdicts):
        raise QaPlanReviewError(
            "agent review cases do not match durable execution results"
        )
    return folded


def reviewed_execution_state(
    recorded_results: Sequence[Mapping[str, Any]],
    reviewed_verdicts: Mapping[int, tuple[str, str]],
) -> str:
    """Fold reviewer verdicts into every durable execution result."""
    state = "passed"
    for result in _reviewed_results(recorded_results, reviewed_verdicts):
        state = aggregate_state(state, result)
    return state


def reviewed_release_reason(
    recorded_results: Sequence[Mapping[str, Any]],
    reviewed_verdicts: Mapping[int, tuple[str, str]],
) -> str:
    """Name every failed requirement, recorded before or verdicted by review."""
    failed = [
        int(result["requirement_id"])
        for result in _reviewed_results(recorded_results, reviewed_verdicts)
        if case_failed(result)
    ]
    return case_failed_reason(failed) if failed else REVIEW_COMPLETE_REASON


__all__ = [
    "REVIEW_COMPLETE_REASON",
    "reviewed_execution_state",
    "reviewed_release_reason",
]
