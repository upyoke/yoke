"""Per-file byte budgets for text that agents load or must read.

The line limit counts lines, so prose can still grow sideways. A project
caps chosen files by bytes in ``.yoke/project.config``::

    file_byte_budget=AGENTS.md:4000

Both authored-file checkers (the pre-commit hook and ``yoke check
file-line``) apply these budgets to the files a change touches. A broken
entry fails every check, so a typo can never silently lift a budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

RECOVERY = (
    "shrink the file, or move the text to the one surface that owns it and "
    "leave a pointer; raise the budget in .yoke/project.config only when the "
    "added text is a binding rule with no better owner"
)


@dataclass(frozen=True)
class ByteBudgetFail:
    path: str
    reason: str
    detail: str

    def message(self) -> str:
        return f"{self.path}: {self.reason}: {self.detail}"


def parse_byte_budgets(
    entries: Iterable[str],
) -> tuple[dict[str, int], list[ByteBudgetFail]]:
    """Split raw ``PATH:BYTES`` values into budgets and malformed entries."""
    budgets: dict[str, int] = {}
    broken: list[ByteBudgetFail] = []
    for entry in entries:
        path, _, raw_bytes = entry.rpartition(":")
        path = path.strip()
        try:
            limit = int(raw_bytes.strip())
        except ValueError:
            limit = 0
        if not path or limit <= 0:
            broken.append(ByteBudgetFail(
                entry or "(empty)",
                "file_byte_budget_malformed",
                "write file_byte_budget=PATH:BYTES with a positive byte count",
            ))
        elif path in budgets:
            broken.append(ByteBudgetFail(
                path,
                "file_byte_budget_duplicate",
                "keep one file_byte_budget entry per path",
            ))
        else:
            budgets[path] = limit
    return budgets, broken


def byte_budget_failures(
    entries: Iterable[str],
    changed_paths: Iterable[str],
    *,
    size_of: Callable[[str], Optional[int]],
) -> list[ByteBudgetFail]:
    """Return every budget a change breaks, plus every broken entry.

    ``size_of`` returns the new byte size of a path, or ``None`` when the
    path no longer exists; a budget for a missing file is stale config.
    """
    budgets, failures = parse_byte_budgets(entries)
    for path, limit in sorted(budgets.items()):
        if size_of(path) is None:
            failures.append(ByteBudgetFail(
                path,
                "file_byte_budget_stale",
                "the budgeted file does not exist; remove its file_byte_budget entry",
            ))
    for path in sorted(set(changed_paths) & set(budgets)):
        size = size_of(path)
        if size is not None and size > budgets[path]:
            failures.append(ByteBudgetFail(
                path,
                "file_byte_budget_exceeded",
                f"{size} bytes, budget {budgets[path]} "
                f"(over by {size - budgets[path]}); {RECOVERY}",
            ))
    return failures


def new_size_reader(
    repo_root: Path, *, staged: bool, run_git: Callable[..., Any],
) -> Callable[[str], Optional[int]]:
    """Read a path's new size: the staged blob, or the working-tree file."""

    def staged_size(path: str) -> Optional[int]:
        result = run_git(["cat-file", "-s", f":{path}"], repo_root=repo_root)
        return int(result.stdout.strip()) if result.returncode == 0 else None

    def worktree_size(path: str) -> Optional[int]:
        target = repo_root / path
        return target.stat().st_size if target.is_file() else None

    return staged_size if staged else worktree_size


def failure_lines(failures: Iterable[ByteBudgetFail]) -> list[str]:
    return [f"  BYTE-BUDGET  {failure.message()}" for failure in failures]


__all__ = (
    "ByteBudgetFail",
    "RECOVERY",
    "byte_budget_failures",
    "failure_lines",
    "new_size_reader",
    "parse_byte_budgets",
)
