"""Require a verdict rationale to identify evidence owned by its case."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.qa_mission_stop_settlement import NON_PROOF_ARTIFACT_TYPES
from yoke_core.domain.qa_plan_review import QaPlanReviewError


class QaVerdictEvidenceUncited(QaPlanReviewError):
    code = "qa_verdict_evidence_uncited"


class QaMissionPassWithoutProductProof(QaPlanReviewError):
    code = "qa_mission_pass_without_product_proof"


def _mission_pass_needs_product_proof(case: Mapping[str, Any]) -> None:
    raise QaMissionPassWithoutProductProof(
        f"Case {case['requirement_id']} is a mission docket with no product "
        "proof: its capture run records only setup, and diagnostic or restore "
        "artifacts are not product proof. Walk the mission, capture what the "
        "product did with `yoke qa artifact add`, then cite that artifact in "
        "the pass. If setup stopped the walk, record fail or undetermined "
        "citing the blocker evidence, or abort the execution as "
        "blocked_on_precondition."
    )


def require_verdict_evidence(
    case: Mapping[str, Any], rationale: str, *, verdict: str
) -> None:
    artifacts = case.get("artifacts") or []
    if verdict == "pass" and case.get("capture_runner") == "agent_mission":
        # A mission's capture run is its preparation docket, so a pass
        # must rest on a product artifact the walk attached.
        accepted = {
            ("artifact", str(artifact["id"]))
            for artifact in artifacts
            if artifact.get("artifact_type") not in NON_PROOF_ARTIFACT_TYPES
        }
        if not accepted:
            _mission_pass_needs_product_proof(case)
    elif artifacts:
        accepted = {("artifact", str(artifact["id"])) for artifact in artifacts}
    else:
        accepted = {("run", str(case["capture_run_id"]))}
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
