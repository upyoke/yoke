"""Readiness validation for File Budget line-pressure facts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.project_contract.file_line_policy import DEFAULT_LIMIT
from yoke_core.domain.file_budget_paths import extract_file_budget_paths
from yoke_core.domain.file_budget_sizing import parse_file_budget_sizing

SIBLING_REQUIRED_THRESHOLD = 330
_SIBLING_PATTERN = re.compile(
    r"\bsibling\b|\bextract\b|\bnew sibling\b|\bsibling module\b",
    re.IGNORECASE,
)


def verify_file_budget_sizing(
    spec_text: str,
    *,
    repo_root: Path,
    issue_type: Callable[..., Any],
) -> list[Any]:
    issues: list[Any] = []
    entries = {entry.path: entry for entry in parse_file_budget_sizing(spec_text)}
    for rel in extract_file_budget_paths(spec_text):
        entry = entries.get(rel)
        if entry is None:
            issues.append(issue_type(
                code="MISSING_FILE_BUDGET_SIZING",
                message=f"File Budget path {rel} has no complete sizing fields",
                remediation=(
                    "record current lines, remaining headroom against 350, "
                    "and the at-or-over-limit flag"
                ),
                context={"path": rel},
            ))
            continue
        candidate = repo_root / rel
        if candidate.exists():
            actual = sum(1 for _ in candidate.open(encoding="utf-8"))
            tolerance = max(2, int(entry.current_line_count * 0.05))
            if abs(actual - entry.current_line_count) > tolerance:
                issues.append(issue_type(
                    code="STALE_LINE_COUNT",
                    message=(
                        f"spec records {rel}={entry.current_line_count} lines "
                        f"but the file currently has {actual} lines"
                    ),
                    remediation=f"refresh the File Budget sizing for {rel}",
                    context={
                        "path": rel, "recorded": entry.current_line_count,
                        "actual": actual,
                    },
                ))
            if actual >= SIBLING_REQUIRED_THRESHOLD and not _SIBLING_PATTERN.search(spec_text):
                issues.append(issue_type(
                    code="MISSING_SIBLING_PLAN",
                    message=(
                        f"{rel} is at {actual} lines (>= "
                        f"{SIBLING_REQUIRED_THRESHOLD}) but has no sibling plan"
                    ),
                    remediation="declare an explicit sibling-module extraction plan",
                    context={"path": rel, "lines": actual},
                ))
        expected_headroom = DEFAULT_LIMIT - entry.current_line_count
        expected_flag = entry.current_line_count >= DEFAULT_LIMIT
        if (
            entry.remaining_headroom != expected_headroom
            or entry.at_or_over_limit != expected_flag
        ):
            issues.append(issue_type(
                code="STALE_FILE_BUDGET_SIZING",
                message=f"File Budget sizing facts disagree for {rel}",
                remediation="recompute headroom and the at-or-over-limit flag",
                context={
                    "path": rel, "recorded": entry.current_line_count,
                    "expected_headroom": expected_headroom,
                    "expected_at_or_over_limit": expected_flag,
                },
            ))
    return issues


__all__ = ["SIBLING_REQUIRED_THRESHOLD", "verify_file_budget_sizing"]
