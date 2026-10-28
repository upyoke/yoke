"""Readiness check: files the spec says it changes must have budget rows.

A spec that declares a File Budget promises that list is the set of files
the work touches. The scope sections (``## Change``, ``## Fix``,
``## Delete``, ``## Scope``, ``## Add`` and their variants) name the files
the work actually changes, so a file named there that already exists but
has no budget row is a budget gap: the path claim will not cover it and
its line pressure was never sized.

Only list items (bulleted or numbered) under those sections count. A
file named under ``## Cause``, ``## Tests`` or in prose is context, not
scope. Only full repo-relative paths (containing ``/``) that exist in
the checkout count, so planned new files and bare filenames are left to
the author. The packaged ``install_bundle_tree/`` mirror is regenerated,
never authored, so it is skipped. Specs without a resolved File Budget are not checked:
the budget is optional for some workflows, and the missing-budget gate
owns the case where it is required.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, List, Set

from yoke_contracts.project_contract.file_line_policy import DEFAULT_LIMIT
from yoke_core.domain.file_budget_paths import (
    extract_file_budget_paths_set,
    has_resolved_file_budget,
    is_path_token,
)

SCOPED_PATH_NOT_IN_FILE_BUDGET = "SCOPED_PATH_NOT_IN_FILE_BUDGET"
SCOPE_HEADING_PREFIXES = ("Change", "Fix", "Delete", "Scope", "Add")
_MIRROR_SEGMENT = "install_bundle_tree/"

_LEVEL2_HEADER = re.compile(r"^## (?P<title>.*)$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s")
_BACKTICKED = re.compile(r"`([^`]+)`")
# ``path.py:96-100`` and ``path.py:12,16`` cite lines of a file.
_LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*$")


def _is_scope_heading(title: str) -> bool:
    return title.strip().startswith(SCOPE_HEADING_PREFIXES)


def scoped_paths(spec_text: str) -> List[str]:
    """Repo-relative paths named in list items under scope headings."""
    in_scope = False
    seen: Set[str] = set()
    paths: List[str] = []
    for line in (spec_text or "").splitlines():
        heading = _LEVEL2_HEADER.match(line.strip())
        if heading:
            in_scope = _is_scope_heading(heading.group("title"))
            continue
        if not in_scope or not _LIST_ITEM.match(line):
            continue
        for match in _BACKTICKED.finditer(line):
            candidate = _LINE_SUFFIX.sub("", match.group(1))
            if "/" not in candidate or not is_path_token(candidate):
                continue
            if _MIRROR_SEGMENT in candidate or candidate in seen:
                continue
            seen.add(candidate)
            paths.append(candidate)
    return paths


def budget_row(path: str, lines: int) -> str:
    """A File Budget row the sizing check accepts, ready to paste."""
    flag = str(lines >= DEFAULT_LIMIT).lower()
    return (
        f"- `{path}` — current {lines} lines; remaining headroom "
        f"{DEFAULT_LIMIT - lines}; at-or-over-limit: {flag}; "
        "responsibility: <what this item changes here>."
    )


def verify_scoped_paths_in_file_budget(
    spec_text: str,
    *,
    repo_root: Path,
    issue_type: Callable[..., Any],
) -> List[Any]:
    """One blocking issue per existing scoped file without a budget row."""
    if not has_resolved_file_budget(spec_text):
        return []
    budget = extract_file_budget_paths_set(spec_text)
    issues: List[Any] = []
    for rel in scoped_paths(spec_text):
        if rel in budget:
            continue
        candidate = repo_root / rel
        if not candidate.is_file():
            continue
        with candidate.open(encoding="utf-8", errors="replace") as handle:
            lines = sum(1 for _ in handle)
        row = budget_row(rel, lines)
        issues.append(issue_type(
            code=SCOPED_PATH_NOT_IN_FILE_BUDGET,
            message=(
                f"{rel} ({lines} lines) is named in a scope section of the "
                "spec but has no File Budget row"
            ),
            remediation=(
                f"add this row to ## File Budget (and widen the path claim "
                f"if claims are on), or move the mention out of the scope "
                f"section if the file only gives context:\n{row}"
            ),
            context={"path": rel, "lines": lines, "row": row},
        ))
    return issues


__all__ = [
    "SCOPED_PATH_NOT_IN_FILE_BUDGET",
    "SCOPE_HEADING_PREFIXES",
    "budget_row",
    "scoped_paths",
    "verify_scoped_paths_in_file_budget",
]
