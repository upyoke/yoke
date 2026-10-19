"""Require an executable case or a real domain-owned discharge path."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# These kinds have explicit verdict writers rather than a case runner.
DOMAIN_DISCHARGE_KINDS = frozenset(
    {
        "simulation",
        "implementation_review",
        "no_tests_declared",
        "deployment_stage_acceptance",
    }
)


def proof_refusal(row: Mapping[str, Any], *, subject: str) -> str:
    """Name the missing proof and recovery before any requirement is written."""
    if str(row.get("blocking_mode") or "blocking") != "blocking":
        return ""
    if str(row.get("method_id") or "").strip():
        return ""
    if row.get("qa_kind") in DOMAIN_DISCHARGE_KINDS:
        return ""
    criterion = (
        row.get("expected_outcome") or row.get("instructions") or row.get("qa_kind")
    )
    return (
        f"requirement_proof_required: {subject}, criterion {criterion!r}, "
        "has no runnable method. Attach the plan case that proves this criterion "
        "with yoke qa item-plan attach, then yoke qa plan materialize; or add a "
        "registered --method-id with instructions, expected outcome and method config. "
        "Copying or transferring a requirement must retain its executable case."
    )
