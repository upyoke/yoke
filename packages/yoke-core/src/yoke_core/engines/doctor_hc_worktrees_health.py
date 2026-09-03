"""Worktree health check — uncommitted, stale, and stranded lanes.

Cluster: HC-worktree-health (single HC). Inspects ``git worktree list``,
the configured ``.worktrees`` directory, local item branches, and the
universal ``item_worktrees`` registry. A lane whose item is terminal but
which is still on disk is reported with the reason it survived — the same
proofs the landing cleanup and the merged-lane sweep apply — rolled up on
one line ("N released lanes still on disk: dirty (...), locked (...),
unregistered directory (...)") ahead of the per-lane detail, so an operator
sees what needs a decision before reading the list.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.engines.merge_landed_lane_cleanup import (
    assess_landed_lane,
    assess_worktree_residue,
    prune_landed_lane,
)
from yoke_core.engines.merge_prune_authority import (
    item_cleanup_authority_blocks_prune,
)

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)
from yoke_core.engines.doctor_tree_scan import list_directory

_TERMINAL = ("done", "cancelled")
# Summary order: what needs an operator first, what the next landing sweeps last.
_STRANDED_ORDER = (
    "dirty",
    "locked",
    "unregistered directory",
    "claimed",
    "unmerged",
    "preserved",
    "sweep-ready",
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _git_for_repo(repo_root: str):
    def run(command, *, cwd=None, capture=True):
        return _base._run(["git", "-C", repo_root, *command])

    return run


def _authority_block(conn, item_id: int) -> str:
    required = ("work_claims", "path_claims", "harness_sessions")
    if not all(_base._table_exists(conn, table) for table in required):
        return "cleanup authority schema is unavailable"
    if item_cleanup_authority_blocks_prune(conn, item_id):
        return "cleanup authority is active or unreadable"
    return ""


def _worktree_entries(porcelain: str) -> List[dict]:
    """Registered worktrees with their branch and git's lock note, if any."""
    entries: List[dict] = []
    current: dict = {}
    for line in [*porcelain.splitlines(), ""]:
        if line.startswith("worktree "):
            current = {"path": line[len("worktree ") :]}
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :].removeprefix("refs/heads/")
        elif line == "locked" or line.startswith("locked "):
            current["locked"] = line.removeprefix("locked").strip() or "no reason recorded"
        elif line == "" and current:
            entries.append(current)
            current = {}
    return entries


def _stranded_category(entry: dict, residue, assessment) -> tuple[str, str]:
    """Name why a terminal item's lane is still on disk, operator-first."""
    if "locked" in entry:
        return "locked", entry["locked"]
    if residue is not None and not residue.safe:
        count = len(residue.precious_paths)
        return "dirty", f"{count} modified file{'s' if count != 1 else ''}"
    if assessment.safe:
        return "sweep-ready", ""
    reason = assessment.reason
    if "authority" in reason:
        return "claimed", reason.split("preserved: ", 1)[-1]
    if "not merged" in reason:
        return "unmerged", reason.split("preserved: ", 1)[-1]
    return "preserved", reason.split("preserved: ", 1)[-1]


def _summary(stranded: Dict[str, List[str]]) -> str:
    total = sum(len(refs) for refs in stranded.values())
    parts = [
        f"{category} ({', '.join(stranded[category])})"
        for category in _STRANDED_ORDER
        if stranded.get(category)
    ]
    plural = "s" if total != 1 else ""
    return f"- {total} released lane{plural} still on disk: " + ", ".join(parts)


def hc_worktree_health(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-worktree-health: Worktree health."""
    issues: List[str] = []
    fixed: List[str] = []
    stranded: Dict[str, List[str]] = {}

    r = _base._run(["git", "worktree", "list", "--porcelain"])
    if r.returncode != 0:
        rec.record("HC-worktree-health", "Worktree health", "PASS", "")
        return
    entries = _worktree_entries(r.stdout)
    registered_paths = {e.get("path", "") for e in entries}
    repo_root = _base._resolve_repo_root()

    for entry in entries:
        wt_path = entry.get("path", "")
        branch = entry.get("branch", "")
        if branch in ("main", "master") or not wt_path:
            continue
        root = str(repo_root or Path(wt_path).parents[1])

        # Repository-declared ignored residue is disposable lane state.
        residue = None
        if Path(wt_path).is_dir():
            residue = assess_worktree_residue(_git_for_repo(root), wt_path)
            if not residue.safe:
                issues.append(
                    f"- Worktree {branch} at {wt_path} has uncommitted changes "
                    f"({residue.reason})"
                )

        # Check terminal ownership through the universal registry.
        p = _p(conn)
        owners = query_rows(
            conn,
            "SELECT DISTINCT iw.item_id, i.status, "
            "COALESCE(p.default_branch, 'main') AS target_branch "
            "FROM item_worktrees iw "
            "JOIN items i ON i.id = iw.item_id "
            "JOIN projects p ON p.id = i.project_id "
            f"WHERE iw.branch = {p} OR iw.path = {p}",
            (branch, wt_path),
        )
        for owner in owners:
            if owner["status"] not in _TERMINAL:
                continue
            public_ref = render_item_ref(conn, owner["item_id"])
            assessment = assess_landed_lane(
                repo_root=root,
                branch=branch,
                target=str(owner["target_branch"]),
                run_git=_git_for_repo(root),
                refresh_target=False,
                authority_block=_authority_block(conn, int(owner["item_id"])),
            )
            category, detail = _stranded_category(entry, residue, assessment)
            label = assessment.reason
            if category == "sweep-ready":
                label = "verified-safe; the next landing on this machine sweeps it"
            elif category in ("locked", "dirty"):
                label = f"worktree is {category} ({detail})"
            if args.fix and category == "sweep-ready":
                preserved = prune_landed_lane(
                    repo_root=root,
                    branch=branch,
                    target=str(owner["target_branch"]),
                    item_id=int(owner["item_id"]),
                    run_git=_git_for_repo(root),
                    emit=lambda *_a, **_kw: None,
                )
                if not preserved:
                    fixed.append(f"- Fixed: removed terminal lane {branch} at {wt_path} — {public_ref}")
                    continue
                category, label = "preserved", preserved[0]
            stranded.setdefault(category, []).append(
                f"{public_ref}: {detail}" if detail else public_ref
            )
            issues.append(f"- Terminal-item lane: {branch} at {wt_path} — {public_ref} is {owner['status']}; {label}")

    # Directories under .worktrees that git no longer registers.
    if repo_root:
        wt_dir = Path(repo_root) / ".worktrees"
        if wt_dir.is_dir():
            for child in list_directory(wt_dir):
                if not child.is_dir():
                    continue
                child_str = str(child)
                if child_str in registered_paths:
                    continue
                p = _p(conn)
                owners = query_rows(
                    conn,
                    "SELECT DISTINCT iw.item_id, i.status "
                    "FROM item_worktrees iw "
                    "JOIN items i ON i.id = iw.item_id "
                    f"WHERE iw.path = {p}",
                    (child_str,),
                )
                for owner in owners:
                    if owner["status"] in _TERMINAL:
                        public_ref = render_item_ref(conn, owner["item_id"])
                        stranded.setdefault("unregistered directory", []).append(public_ref)
                        issues.append(
                            f"- Stale worktree directory: {child_str} "
                            f"— {public_ref} is {owner['status']} "
                            "(unregistered directory preserved for inspection)"
                        )

    # Detect stale local branches for done/cancelled items
    done_rows = query_rows(
        conn,
        "SELECT DISTINCT iw.item_id, iw.branch, "
        "COALESCE(p.default_branch, 'main') AS target_branch "
        "FROM item_worktrees iw "
        "JOIN items i ON i.id = iw.item_id "
        "JOIN projects p ON p.id = i.project_id "
        "WHERE i.status IN ('done', 'cancelled')",
    )
    for row in done_rows:
        did = row["item_id"]
        branch = row["branch"]
        br = _base._run(["git", "rev-parse", "--verify", branch])
        if repo_root and br.returncode == 0 and branch not in {entry.get("branch", "") for entry in entries}:
            authority_block = _authority_block(conn, int(did))
            assessment = assess_landed_lane(
                repo_root=str(repo_root),
                branch=branch,
                target=str(row["target_branch"]),
                run_git=_git_for_repo(str(repo_root)),
                refresh_target=False,
                authority_block=authority_block,
            )
            if args.fix and assessment.safe:
                preserved = prune_landed_lane(
                    repo_root=str(repo_root),
                    branch=branch,
                    target=str(row["target_branch"]),
                    item_id=int(did),
                    run_git=_git_for_repo(str(repo_root)),
                    emit=lambda *_a, **_kw: None,
                )
                if not preserved:
                    fixed.append(f"- Fixed: deleted terminal local branch {branch}")
                    continue
            issues.append(
                f"- Stale local branch: {branch} — {render_item_ref(conn, did)}; {assessment.reason or 'verified-safe'}"
            )

    # Terminal updates release operational lanes but retain audit history.
    wt_rows = query_rows(
        conn,
        "SELECT i.id, iw.branch FROM items i "
        "JOIN item_worktrees iw ON iw.item_id = i.id "
        "WHERE i.status IN ('done', 'cancelled') AND iw.state = 'active'",
    )
    for row in wt_rows:
        issues.append(
            f"- Active worktree lane on terminal item: {render_item_ref(conn, row['id'])} "
            f"has branch='{row['branch']}' "
            "(release the lane while preserving its audit record)"
        )

    if stranded:
        issues.insert(0, _summary(stranded))
    if issues:
        detail = [*fixed, *issues]
        rec.record("HC-worktree-health", "Worktree health", "WARN", "\n".join(detail))
    elif fixed:
        rec.record("HC-worktree-health", "Worktree health", "PASS", "\n".join(fixed))
    else:
        rec.record("HC-worktree-health", "Worktree health", "PASS", "")
