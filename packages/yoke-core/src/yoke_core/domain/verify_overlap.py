"""Worktree-plan file-overlap verifier.

Direct Python owner — callers invoke via ``python3 -m yoke_core.domain.verify_overlap``.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import TextIO


WORKTREE_RE = re.compile(r"^## Worktree:\s*(.+?)\s*$")
FILE_BULLET_RE = re.compile(r"^\s*-\s*(.+?)\s*$")
SECTION_RE = re.compile(r"^##\s+")
DEP_GROUP_RE = re.compile(r"^\s*-\s*([^:]+):\s*(.+?)\s*$")


def _parse_plan(plan_path: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    worktree_files: dict[str, set[str]] = defaultdict(set)
    dependency_groups: dict[str, set[str]] = defaultdict(set)

    current_worktree = ""
    in_files = False
    in_dep_groups = False

    for raw_line in plan_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip("\n")
        match = WORKTREE_RE.match(line)
        if match:
            current_worktree = match.group(1)
            in_files = False
            in_dep_groups = False
            continue

        if line == "Files touched:":
            in_files = True
            in_dep_groups = False
            continue

        if line.startswith("Generated files"):
            in_files = False
            continue

        if line.startswith("## Dependency group") or line.startswith("## Dependency Group"):
            in_dep_groups = True
            in_files = False
            current_worktree = ""
            continue

        if SECTION_RE.match(line):
            in_files = False
            if not line.startswith("## Dependency group") and not line.startswith("## Dependency Group"):
                in_dep_groups = False
            if not line.startswith("## Worktree:"):
                current_worktree = ""
            continue

        if in_files and current_worktree:
            bullet = FILE_BULLET_RE.match(line)
            if bullet:
                file_path = re.sub(r"\s+\(.*$", "", bullet.group(1)).strip()
                if file_path:
                    worktree_files[current_worktree].add(file_path)
            continue

        if in_dep_groups:
            match = DEP_GROUP_RE.match(line)
            if match:
                group_name = match.group(1).strip()
                files = {
                    item.strip()
                    for item in match.group(2).split(",")
                    if item.strip()
                }
                if files:
                    dependency_groups[group_name].update(files)

    return worktree_files, dependency_groups


def verify_overlap(
    plan_path: str,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    if out is None:
        out = sys.stdout
    if err is None:
        err = sys.stderr

    path = Path(plan_path)
    if not path.is_file():
        print(f"Error: Worktree plan not found: {plan_path}", file=err)
        return 1

    worktree_files, dependency_groups = _parse_plan(path)
    if not worktree_files:
        print("Warning: No file lists found in worktree plan. Check plan format.", file=err)
        return 0

    overlap_found = False

    file_to_worktrees: dict[str, list[str]] = defaultdict(list)
    for worktree, files in worktree_files.items():
        for file_path in files:
            file_to_worktrees[file_path].append(worktree)

    for file_path in sorted(file_to_worktrees):
        worktrees = sorted(set(file_to_worktrees[file_path]))
        if len(worktrees) > 1:
            print(
                f"OVERLAP: {file_path} appears in worktrees: {' '.join(worktrees)}",
                file=err,
            )
            overlap_found = True

    for group_name, files in sorted(dependency_groups.items()):
        touched = sorted(
            {
                worktree
                for worktree, wt_files in worktree_files.items()
                if any(file in wt_files for file in files)
            }
        )
        if len(touched) > 1:
            print(
                f"LOGICAL OVERLAP: dependency group '{group_name}' has files modified in worktrees: {' '.join(touched)}",
                file=err,
            )
            overlap_found = True

    if overlap_found:
        print("", file=err)
        print("File overlap check: FAIL — overlaps detected across worktrees", file=err)
        return 1

    print("File overlap check: PASS — no overlaps across worktrees", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0]:
        print("Usage: python3 -m yoke_core.domain.verify_overlap <worktree-plan.md>", file=sys.stderr)
        return 1
    return verify_overlap(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
