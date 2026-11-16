"""Targeted numeric replacements for File Budget sizing facts."""

from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class RepairedPath:
    path: str
    recorded: int
    actual: int


def _path_pattern(path: str) -> re.Pattern:
    from yoke_core.domain.file_budget_sizing import path_sizing_pattern

    return path_sizing_pattern(path)


def apply_stale_count_replacements(
    spec_text: str,
    repairs: List[RepairedPath],
    limit: int,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Apply each repair's new count against ``limit``; refuse missing or
    duplicate matches."""
    refused: List[Dict[str, Any]] = []
    text = spec_text or ""
    for r in repairs:
        pattern = _path_pattern(r.path)
        matches = list(pattern.finditer(text))
        if not matches:
            refused.append(
                {
                    "path": r.path,
                    "reason": "missing_file_budget_entry",
                    "recorded": r.recorded,
                    "actual": r.actual,
                }
            )
            continue
        if len(matches) > 1:
            refused.append(
                {
                    "path": r.path,
                    "reason": "duplicate_count_match",
                    "recorded": r.recorded,
                    "actual": r.actual,
                    "match_count": len(matches),
                }
            )
            continue
        from yoke_core.domain.file_budget_sizing import replacement_for_current_size

        text = pattern.sub(
            lambda match, count=r.actual: replacement_for_current_size(
                match,
                count,
                limit,
            ),
            text,
            count=1,
        )
    return text, refused


def stale_issue_limit(issues: List[Dict[str, Any]]) -> Optional[int]:
    """The line limit the readiness check sized these stale counts against.

    Clients released before the limit rode the issue context sized every
    count against the default, so an issue without one means the default.
    ``None`` means the issues disagree or carry an unusable limit.
    """
    from yoke_contracts.project_contract.file_line_policy import DEFAULT_LIMIT

    limits = {
        (issue.get("context") or {}).get("limit", DEFAULT_LIMIT) for issue in issues
    }
    if len(limits) != 1:
        return None
    (limit,) = limits
    return limit if isinstance(limit, int) and limit > 0 else None


def resolve_repairs(
    issues: List[Dict[str, Any]],
    root: Optional[Path],
) -> Tuple[List[RepairedPath], List[Dict[str, Any]]]:
    """Pair each stale count with the path's real length.

    ``root`` is ``None`` on a host without the item project's checkout,
    where the real length is the one the machine that ran the check
    reported rather than one read here.
    """
    from yoke_core.domain.idea_readiness_repair_handoff import live_line_count

    repairs: List[RepairedPath] = []
    refused: List[Dict[str, Any]] = []
    for issue in issues:
        ctx = issue.get("context") or {}
        path = str(ctx.get("path") or "")
        recorded_raw = ctx.get("recorded")
        if not path or recorded_raw is None:
            refused.append({"reason": "missing_context", "issue": issue})
            continue
        try:
            recorded = int(recorded_raw)
        except (TypeError, ValueError):
            refused.append({"reason": "non_integer_recorded", "path": path})
            continue
        actual = live_line_count(root, path, dict(ctx))
        if actual is None:
            refused.append(
                {"path": path, "reason": "missing_file", "recorded": recorded}
            )
            continue
        repairs.append(RepairedPath(path=path, recorded=recorded, actual=actual))
    return repairs, refused
