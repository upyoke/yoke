"""Recovery text for terminal QA requirements lacking current proof."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoke_core.domain.qa_terminal_settlement import BlockingRequirementIssue


def requirement_issue_errors(
    issues: list[BlockingRequirementIssue],
    *,
    public_ref: str,
    target_status: str,
) -> list[str]:
    """Render actionable missing, incomplete, and stale-SHA refusals."""
    if not issues:
        return []
    errors = [
        f"Error: Cannot transition {public_ref} to {target_status!r} -- "
        f"{len(issues)} blocking QA requirement(s) lack a completed verdict "
        "for the merging commit.",
        "  A waiver is an explicit, recorded, requirement-scoped operator "
        "override; it is not part of the normal merge recipe.",
    ]
    errors.extend(
        f"  - Requirement #{issue.requirement_id} [{issue.state}]: "
        f"{issue.detail}. {issue.recovery}."
        for issue in issues
    )
    return errors


def _recovery_instruction(requirement: dict[str, Any]) -> str:
    requirement_id = str(requirement.get("id") or "<unknown>")
    case_command = f"yoke qa case run --requirement-id {requirement_id}"
    method_id = str(requirement.get("method_id") or "")
    source = str(requirement.get("requirement_source") or "")
    evidence_instruction = (
        "Record the existing exact-head CI result for this requirement through "
        "`yoke qa run record-verdict --help`, passing --raw-result as JSON "
        'carrying the CI run id/URL and {"verification_tree": {"head_sha": '
        '"<the commit that run verified>"}} -- prose is stored verbatim, '
        "leaves the head SHA unreadable, and this gate refuses again"
    )
    if source == "flow_derived":
        return evidence_instruction
    if method_id != "command-ci":
        return f"Run `{case_command}`"
    from yoke_core.domain.qa_method_config_validation import (
        QaMethodConfigError,
        validate_method_config,
    )

    raw_config = requirement.get("method_config")
    try:
        method_config = (
            raw_config
            if isinstance(raw_config, dict)
            else json.loads(str(raw_config or "{}"))
        )
    except (TypeError, ValueError):
        method_config = {}
    try:
        validate_method_config("command-ci", method_config)
    except QaMethodConfigError:
        return "The stored CI case is not executable; " + evidence_instruction
    return f"Run `{case_command}`"
