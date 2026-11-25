"""Require a verdict rationale to identify evidence owned by its case."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.qa_plan_review import QaPlanReviewError


class QaVerdictEvidenceUncited(QaPlanReviewError):
    code = "qa_verdict_evidence_uncited"


def require_verdict_evidence(case: Mapping[str, Any], rationale: str) -> None:
    artifacts = case.get("artifacts") or []
    accepted = (
        {("artifact", str(artifact["id"])) for artifact in artifacts}
        if artifacts
        else {("run", str(case["capture_run_id"]))}
    )
    # Match whole IDs and exclude fragments of decimals or hyphenated identifiers.
    citations = set(
        re.findall(
            r"(?<![\w-])(artifact|run)\s+(\d+)(?![\w-]|\.\d)",
            rationale.lower(),
        )
    )
    if accepted.isdisjoint(citations):
        choices = ", ".join(
            f"{kind} {identifier}" for kind, identifier in sorted(accepted)
        )
        raise QaVerdictEvidenceUncited(
            f"Case {case['requirement_id']} has no evidence citation in its verdict. "
            f"Cite one of {choices} in the rationale and resubmit."
        )
