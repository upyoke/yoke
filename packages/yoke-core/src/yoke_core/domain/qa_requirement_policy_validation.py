"""Shared QA requirement-add validation and help text."""

from __future__ import annotations

import json
from typing import Optional, Sequence

from yoke_core.domain.qa_constants import (
    VALID_BROWSER_QA_KINDS,
    VALID_REQUIREMENT_SOURCES,
)


def _format_values(values: Sequence[str]) -> str:
    return ", ".join(values)


REQUIREMENT_SOURCE_HELP = (
    "Requirement source. Valid values: "
    f"{_format_values(VALID_REQUIREMENT_SOURCES)}."
)

QA_KIND_HELP = (
    "Requirement kind. Browser kinds "
    f"({_format_values(VALID_BROWSER_QA_KINDS)}) require --success-policy."
)

BROWSER_SUCCESS_POLICY_SHAPE = (
    '{"steps":[{"action":"navigate","route":"/"},'
    '{"action":"screenshot","capture":true}]}'
)

SUCCESS_POLICY_HELP = (
    f"JSON policy. Required for {_format_values(VALID_BROWSER_QA_KINDS)} with shape "
    f"{BROWSER_SUCCESS_POLICY_SHAPE}. ac_verification may omit this or use "
    '{"min_runs":N,"min_pass":N}.'
)


def validate_success_policy(
    qa_kind: str,
    success_policy: Optional[str],
    *,
    label: str = "",
) -> list[str]:
    """Return argparse-friendly errors for qa_kind-specific policy rules."""
    if qa_kind not in VALID_BROWSER_QA_KINDS:
        return []

    prefix = f"{label}: " if label else ""
    if not success_policy:
        return [
            f"{prefix}--success-policy is required when --qa-kind={qa_kind}.",
            f"{prefix}Expected shape: {BROWSER_SUCCESS_POLICY_SHAPE}",
        ]

    try:
        policy = json.loads(success_policy)
    except json.JSONDecodeError:
        return _shape_errors(prefix, qa_kind, success_policy)

    if not isinstance(policy, dict):
        return _shape_errors(prefix, qa_kind, success_policy)
    steps = policy.get("steps")
    if not isinstance(steps, list):
        return _shape_errors(prefix, qa_kind, success_policy)

    missing_action = sum(
        1 for step in steps if not isinstance(step, dict) or "action" not in step
    )
    if missing_action:
        return [
            (
                f"{prefix}{qa_kind} success_policy has {missing_action} "
                "step(s) missing the 'action' field."
            ),
            (
                f"{prefix}Every step must have an action "
                "(navigate, assert, screenshot, click, type, wait, scroll)."
            ),
            f"{prefix}See: docs/browser-scenario-schema.md",
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


def _shape_errors(prefix: str, qa_kind: str, got: str) -> list[str]:
    return [
        (
            f"{prefix}{qa_kind} requirements require success_policy "
            "with a 'steps' array."
        ),
        f"{prefix}Expected: {BROWSER_SUCCESS_POLICY_SHAPE}",
        f"{prefix}Got: {got}",
        f"{prefix}See: docs/browser-scenario-schema.md",
    ]
