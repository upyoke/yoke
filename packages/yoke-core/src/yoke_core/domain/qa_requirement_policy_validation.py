"""Shared QA requirement-add validation and help text."""

from __future__ import annotations

from typing import Optional, Sequence

from yoke_core.domain.qa_constants import (
    VALID_REQUIREMENT_SOURCES,
)


def _format_values(values: Sequence[str]) -> str:
    return ", ".join(values)


REQUIREMENT_SOURCE_HELP = (
    "Requirement source. Valid values: "
    f"{_format_values(VALID_REQUIREMENT_SOURCES)}."
)

QA_KIND_HELP = (
    "Aggregate requirement kind. Executable cases are materialized from "
    "registered test-plan methods."
)

SUCCESS_POLICY_HELP = (
    "Optional aggregate requirement policy. Method-backed cases use their "
    "immutable method_config snapshot instead."
)


def validate_success_policy(
    qa_kind: str,
    success_policy: Optional[str],
    *,
    label: str = "",
) -> list[str]:
    """Retain the generic add-path hook without method-specific authoring."""
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
