"""Result vocabulary for the idea / refine readiness checks.

Three shapes travel together out of ``run_all_checks``:

- ``Issue`` — a defect in the item the author can fix.
- ``UnavailableValidation`` — a check that could NOT be performed on the
  executing host, naming the check, the reason, and a recovery that is
  actually supported there. Never a pass, never a retry: the host is
  missing an input no rerun on that host can produce.
- ``ReadinessOutcome`` — the composed answer, plus the ``verdict`` and
  ``classification`` every caller reads instead of recomputing them.

``classify_readiness_issues`` buckets an issues list for refine-entry
routing and lives here so the outcome can classify itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

CLASS_PASS = "pass"
CLASS_PURE_STALE_COUNT = "pure_stale_count"
CLASS_MIXED_STALE_COUNT = "mixed_stale_count"
CLASS_UNRECOVERABLE = "unrecoverable"
CLASS_UNAVAILABLE = "unavailable"

VERDICT_PASS = "pass"
VERDICT_BLOCK = "block"
VERDICT_UNAVAILABLE = "unavailable"

_STALE_CODE = "STALE_LINE_COUNT"
_RECOVERABLE_CLAIM_CODES = frozenset({
    "FILE_BUDGET_NOT_IN_CLAIM", "CLAIM_NOT_IN_FILE_BUDGET",
    "cross_item_overlap", "MISSING_FILE_BUDGET",
})


@dataclass
class Issue:
    code: str
    message: str
    remediation: str
    context: dict = field(default_factory=dict)


@dataclass(frozen=True)
class UnavailableValidation:
    """One readiness check the executing host could not perform."""

    check: str
    reason: str
    recovery: str
    retryable: bool = False
    context: dict = field(default_factory=dict)


@dataclass
class ReadinessOutcome:
    """Everything one readiness run learned, and what it could not learn."""

    issues: List[Issue] = field(default_factory=list)
    unavailable: List[UnavailableValidation] = field(default_factory=list)
    advisories: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.issues:
            return VERDICT_BLOCK
        if self.unavailable:
            return VERDICT_UNAVAILABLE
        return VERDICT_PASS

    @property
    def classification(self) -> str:
        if self.unavailable and not self.issues:
            return CLASS_UNAVAILABLE
        return classify_readiness_issues(self.issue_payloads())

    def issue_payloads(self) -> List[Dict[str, Any]]:
        return [
            {"code": i.code, "message": i.message,
             "remediation": i.remediation, "context": i.context}
            for i in self.issues
        ]

    def unavailable_payloads(self) -> List[Dict[str, Any]]:
        return [
            {"check": u.check, "reason": u.reason, "recovery": u.recovery,
             "retryable": u.retryable, "context": u.context}
            for u in self.unavailable
        ]


def classify_readiness_issues(issues: List[Dict[str, Any]]) -> str:
    """Bucket a readiness-check issues list for refine-entry routing.

    Issue-code sets that contain at least one recoverable claim-coverage
    code and no codes outside the recoverable set route through
    ``CLASS_MIXED_STALE_COUNT``. The historical class name is preserved
    for downstream refine-entry routing compatibility — the branch already
    means "continue into refine for claim/path repair", which is the right
    destination here.
    """
    if not issues:
        return CLASS_PASS
    codes = {str(i.get("code") or "") for i in issues}
    if codes == {_STALE_CODE}:
        return CLASS_PURE_STALE_COUNT
    if _STALE_CODE in codes and codes - {_STALE_CODE} <= _RECOVERABLE_CLAIM_CODES:
        return CLASS_MIXED_STALE_COUNT
    if codes and codes <= _RECOVERABLE_CLAIM_CODES:
        return CLASS_MIXED_STALE_COUNT
    return CLASS_UNRECOVERABLE


__all__ = [
    "CLASS_MIXED_STALE_COUNT",
    "CLASS_PASS",
    "CLASS_PURE_STALE_COUNT",
    "CLASS_UNAVAILABLE",
    "CLASS_UNRECOVERABLE",
    "Issue",
    "ReadinessOutcome",
    "UnavailableValidation",
    "VERDICT_BLOCK",
    "VERDICT_PASS",
    "VERDICT_UNAVAILABLE",
    "classify_readiness_issues",
]
