"""Shared QA requirement-add validation and help text."""

from __future__ import annotations

import json
from typing import Optional, Sequence

from yoke_core.domain.qa_constants import (
    VALID_REQUIREMENT_SOURCES,
)


def _format_values(values: Sequence[str]) -> str:
    return ", ".join(values)


REQUIREMENT_SOURCE_HELP = (
    f"Requirement source. Valid values: {_format_values(VALID_REQUIREMENT_SOURCES)}."
)

QA_KIND_HELP = (
    "Aggregate requirement kind. Executable cases are materialized from "
    "registered test-plan methods."
)

SUCCESS_POLICY_HELP = (
    "All-pass requirement policy. Grade only the current actual attempt; "
    "method_config may measure that attempt against a threshold."
)


def validate_success_policy(
    qa_kind: str,
    success_policy: Optional[str],
    *,
    label: str = "",
) -> list[str]:
    """Reject policies that authorize from historical attempts or voting."""
    if not success_policy or success_policy == "all-pass":
        return []
    prefix = f"{label}: " if label else ""
    try:
        policy = (
            json.loads(success_policy)
            if isinstance(success_policy, str)
            else success_policy
        )
        if not isinstance(policy, dict):
            raise ValueError("policy must be an object")
        if (
            policy.get("id", "all-pass") != "all-pass"
            or policy.get("kind", "all_pass") != "all_pass"
        ):
            raise ValueError("only all-pass aggregation is supported")
        if any(key in policy for key in ("min_runs", "min_pass_rate")) or policy.get(
            "type"
        ) in ("statistical", "agent_judgment"):
            raise ValueError(
                "historical attempts cannot vote or rescue a current result"
            )
    except (TypeError, ValueError) as exc:
        return [
            f"{prefix}qa_success_policy_invalid: {exc}. Use all-pass; configure measured thresholds on the single executing method."
        ]
    return []


def validate_requirement_source(source: str, *, label: str = "") -> list[str]:
    if source in VALID_REQUIREMENT_SOURCES:
        return []
    prefix = f"{label}: " if label else ""
    return [
        (
            f"{prefix}--requirement-source must be one of "
            f"{_format_values(VALID_REQUIREMENT_SOURCES)}."
        )
    ]
