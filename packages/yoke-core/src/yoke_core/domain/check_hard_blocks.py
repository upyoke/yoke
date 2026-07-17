"""Shared dependency gate with satisfaction evaluation.

Queries ``item_dependencies`` for blocking entries where the given item is
the dependent, evaluates each blocker's satisfaction condition, and
reports unsatisfied blockers. Exits 0 when clear, 1 when blocked.

CLI contract::

    python3 -m yoke_core.domain.check_hard_blocks <item-id> [--gate-point <point>]

Output format (when blocked, one line per unresolved blocker)::

    BLOCKED|YOK-N|idea|Enforce hard-block item dependencies|activation|status:done
    BLOCKED|YOK-M|implementing|Some other item title|integration|fact:merged
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain import db_helpers
from yoke_core.domain.lifecycle import ISSUE_PROGRESSION
from yoke_core.domain.path_claims_dependency_resolver import _strip_sun_prefix
from yoke_core.domain.project_checkout_locations import checkout_for_project


# Statuses at or past ``implemented`` in the delivery progression.
# Derived from lifecycle.ISSUE_PROGRESSION so this set stays in sync with
# lifecycle evolution.
_AT_OR_PAST_IMPLEMENTED: frozenset[str] = frozenset(
    ISSUE_PROGRESSION[ISSUE_PROGRESSION.index("implemented"):]
)
# Statuses where the branch is known to be merged (post-release).
_MERGED_STATUSES: frozenset[str] = frozenset(
    ISSUE_PROGRESSION[ISSUE_PROGRESSION.index("release"):]
)


def _normalize_item_id(raw: str) -> Optional[int]:
    stripped = raw.strip()
    if stripped.upper().startswith("YOK-"):
        stripped = stripped[4:]
    stripped = stripped.lstrip("0")
    if stripped == "":
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def _query_blockers(
    conn,
    item_id: int,
    gate_filter: Optional[str] = None,
) -> List[Tuple[str, str, str]]:
    """Return ``[(blocking_item, gate_point, satisfaction), ...]``.

    ``dependent_item`` stores public text refs whose shape may vary
    (``YOK-N``, bare numeric, zero-padded); rows are matched through the
    same ``_strip_sun_prefix`` normalizer the overlap classifier uses so
    every shape gates lifecycle exactly like it serializes claims.
    """
    dependent = str(item_id)
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    if gate_filter:
        rows = db_helpers.query_rows(
            conn,
            "SELECT dependent_item, blocking_item, gate_point, satisfaction "
            f"FROM item_dependencies WHERE gate_point = {p} "
            "ORDER BY blocking_item",
            (gate_filter,),
        )
    else:
        rows = db_helpers.query_rows(
            conn,
            "SELECT dependent_item, blocking_item, gate_point, satisfaction "
            "FROM item_dependencies ORDER BY blocking_item",
            (),
        )
    return [
        (row["blocking_item"], row["gate_point"], row["satisfaction"])
        for row in rows
        if _strip_sun_prefix(row["dependent_item"]) == dependent
    ]


def _query_item(conn, item_id: int) -> Optional[dict]:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = db_helpers.query_one(
        conn,
        "SELECT i.status, i.title, i.worktree, p.slug AS project, i.merged_at "
        "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {p}",
        (item_id,),
    )
    if row is None:
        return None
    return {
        "status": row["status"],
        "title": row["title"],
        "worktree": row["worktree"],
        "project": row["project"],
        "merged_at": row["merged_at"],
    }


def _query_project_repo_path(conn, project: Optional[str]) -> Optional[str]:
    if not project:
        return None
    checkout = checkout_for_project(conn, project)
    return str(checkout) if checkout is not None else None


def _git_root() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return root if root else None


def _branch_is_merged(repo: str, branch: str, base: str = "main") -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", repo, "merge-base", "--is-ancestor", branch, base],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    return result.returncode == 0


def _is_satisfied(satisfaction: str, item: dict, conn) -> bool:
    status = item.get("status") or ""
    if satisfaction == "status:done":
        return status == "done"
    if satisfaction == "status:implemented":
        return status in _AT_OR_PAST_IMPLEMENTED
    if satisfaction == "fact:merged":
        # Prefer the canonical merge fact when available. sqlite returns
        # real None for NULL, so a truthy check is sufficient here.
        if item.get("merged_at"):
            return True
        worktree = item.get("worktree")
        if worktree:
            repo = _query_project_repo_path(conn, item.get("project")) or _git_root()
            if repo and _branch_is_merged(repo, worktree):
                return True
        return status in _MERGED_STATUSES
    # Unknown satisfaction — fail-safe unsatisfied
    return False


def evaluate_blockers(
    item_id: int,
    gate_filter: Optional[str] = None,
) -> List[str]:
    """Return a list of ``BLOCKED|...`` lines for unsatisfied blockers.

    Uses a single DB connection for the entire evaluation (blockers query
    + per-blocker item lookups + optional project lookups) to avoid the
    N+1 connection-open pattern from the original shell port.
    """
    output: list[str] = []
    with db_helpers.connect() as conn:
        blockers = _query_blockers(conn, item_id, gate_filter=gate_filter)
        if not blockers:
            return output

        for blocking_item, gate_point, satisfaction in blockers:
            dep_num = _normalize_item_id(blocking_item)
            if dep_num is None:
                continue
            dep_item = _query_item(conn, dep_num)
            if dep_item is None:
                output.append(
                    "BLOCKED|%s|missing|<unknown>|%s|%s"
                    % (blocking_item, gate_point, satisfaction)
                )
                continue
            if _is_satisfied(satisfaction, dep_item, conn):
                continue
            output.append(
                "BLOCKED|%s|%s|%s|%s|%s"
                % (
                    blocking_item,
                    dep_item.get("status") or "",
                    dep_item.get("title") or "",
                    gate_point,
                    satisfaction,
                )
            )
    return output


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="check-hard-blocks")
    parser.add_argument("item_id", help="Item ID (YOK-N or N)")
    parser.add_argument(
        "--gate-point",
        dest="gate_point",
        default=None,
        help="Optional gate-point filter (activation|integration|closure)",
    )
    args = parser.parse_args(argv)

    number = _normalize_item_id(args.item_id)
    if number is None:
        print("Error: could not parse item ID from %s" % args.item_id, file=sys.stderr)
        return 2

    try:
        lines = evaluate_blockers(number, gate_filter=args.gate_point)
    except Exception as exc:
        print("Error: check-hard-blocks failed: %s" % exc, file=sys.stderr)
        return 2

    if not lines:
        return 0

    for line in lines:
        print(line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
