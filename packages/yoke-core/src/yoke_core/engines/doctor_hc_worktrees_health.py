"""Worktree health check — uncommitted, stale, and stranded lanes.

HC-worktree-health inspects every worktree, local branch and item lane.
The ``item_worktrees`` registry supplies ownership. Terminal lanes still on
disk report the cleanup proof that preserved them, with an operator-first
summary ahead of each lane's detail.

Lane reads run on the checkout machine, with ownership served through
``doctor_worktree_lane_authority``. Unreadable ownership reports N/A. Independent
residue reads overlap under the shared deadline; every lane remains checked.
Terminal lanes are proved by ``doctor_worktree_terminal_lanes`` against one
batched authority read and, under ``--fix``, retired one at a time as each is
proved, so a run the budget cuts short keeps what it already retired.

Detached self-deploy driver trees are checked against their run status and
retired under ``--fix`` once the run is over.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from yoke_core.engines.deploy_run_worktree_naming import (
    run_id_for_driver_worktree,
)
from yoke_core.engines.deploy_run_worktree_retirement import (
    assess_deploy_run_worktrees,
    retire_terminal_deploy_run_worktrees,
)
from yoke_core.engines.doctor_worktree_lane_authority import LaneRow, lane_inventory
from yoke_core.engines.git_worktree_registry import (
    detached_head,
    parse_worktree_porcelain,
)
from yoke_core.engines.doctor_worktree_terminal_lanes import (
    DEPLOY_RUN_CATEGORY,
    TerminalLaneRetirer,
    stranded_category,
    stranded_summary,
)
from yoke_core.engines.lane_residue_declared_paths import declared_disposable_roots
from yoke_core.engines.worktree_removal import finish_tombstones, tombstones
from yoke_core.engines.merge_worktree_cleanliness import assess_lane_residue

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)
from yoke_core.engines.doctor_tree_scan import list_directory
from yoke_core.engines.doctor_parallel_reads import bounded_read_map

_TERMINAL = ("done", "cancelled")
_DEPLOY_RUN_RETIRABLE_LABEL = (
    "verified-safe; this check's --fix retires it, as does the next landing "
    "on this machine"
)


def _git_for_repo(repo_root: str):
    def run(command, *, cwd=None, capture=True):
        return _base._run(["git", "-C", repo_root, *command])

    return run


def _worktree_entries(porcelain: str) -> List[dict]:
    """Registered worktrees with their branch and git's lock note, if any.

    A detached checkout is ``detached@<commit>`` from the shared porcelain
    reader. An empty branch means the record named neither, not a detached HEAD.
    """
    entries: List[dict] = []
    for parsed in parse_worktree_porcelain(porcelain):
        entry = {"path": parsed.path, "branch": parsed.branch}
        if parsed.lock_reason is not None:
            entry["locked"] = parsed.lock_reason or "no reason recorded"
        entries.append(entry)
    return entries


def hc_worktree_health(_conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-worktree-health: Worktree health (ownership reads relay)."""
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

    lanes = lane_inventory(args.project)
    if lanes is None:
        rec.record(
            "HC-worktree-health",
            "Worktree health",
            "N/A",
            f"reads the {args.project} lane registry; this control plane did "
            "not serve item_worktrees.inventory, so lane ownership cannot be "
            "proven from here",
        )
        return
    by_branch: Dict[str, List[LaneRow]] = {}
    by_path: Dict[str, List[LaneRow]] = {}
    for lane in lanes:
        by_branch.setdefault(lane.branch, []).append(lane)
        if lane.path:
            by_path.setdefault(lane.path, []).append(lane)

    # Enumerate once rather than launching Git for every historical lane row.
    branch_refs = _base._run(
        ["git", "for-each-ref", "--format=%(refname:lstrip=2)", "refs/heads"]
    )
    if branch_refs.returncode:
        rec.record(
            "HC-worktree-health",
            "Worktree health",
            "FAIL",
            "Local branch inventory unreadable; retry after Git recovers.",
        )
        return
    local_branches = set(branch_refs.stdout.splitlines())
    live_branches = {entry.get("branch", "") for entry in entries}

    def root_for(path: str) -> str:
        return str(repo_root or Path(path).parents[1])

    # Detached deploy drivers are answered from their run status below.
    lane_entries = [
        e
        for e in entries
        if e.get("branch") not in ("main", "master")
        and e.get("path")
        and not run_id_for_driver_worktree(Path(e["path"]), Path(root_for(e["path"])))
    ]

    def terminal_owners(entry: dict) -> List[LaneRow]:
        owners = {
            lane.public_ref: lane
            for lane in [
                *by_branch.get(entry.get("branch", ""), []),
                *by_path.get(entry["path"], []),
            ]
        }
        return [lane for lane in owners.values() if lane.status in _TERMINAL]

    stale_branches = [
        lane
        for lane in lanes
        if repo_root
        and lane.status in _TERMINAL
        and lane.branch in local_branches
        and lane.branch not in live_branches
    ]
    roots = declared_disposable_roots(repo_root) if repo_root else None
    paths = [e["path"] for e in lane_entries if Path(e["path"]).is_dir()]

    def read_residue(path):
        root = root_for(path)
        lane_roots = roots if roots is not None else declared_disposable_roots(root)
        return assess_lane_residue(_git_for_repo(root), path, lane_roots)

    residues = dict(zip(paths, bounded_read_map(read_residue, paths)))
    retirer = TerminalLaneRetirer(
        [
            *(
                (entry.get("branch", ""), entry["path"])
                for entry in lane_entries
                if terminal_owners(entry)
            ),
            *((lane.branch, lane.path) for lane in stale_branches),
        ],
        fix=args.fix,
        git_for_repo=_git_for_repo,
        residues=residues,
        checkouts=entries,
    )
    if retirer.authority_failure:
        issues.append(
            "- Cleanup authority unreadable: merge.prune.authority_verdicts did "
            f"not answer ({retirer.authority_failure}), so every terminal lane "
            "is preserved; rerun this check with --fix once the control plane "
            "answers it"
        )

    for entry in lane_entries:
        wt_path = entry["path"]
        branch = entry.get("branch", "")
        root = root_for(wt_path)

        # Named or project-declared ignored caches are disposable; anything
        # else is lane content.
        residue = None
        if Path(wt_path).is_dir():
            residue = residues.get(wt_path) or read_residue(wt_path)
            if not residue.disposable:
                issues.append(
                    f"- Worktree {branch} at {wt_path} holds content cleanup "
                    f"preserves ({residue.reason})"
                )

        # Check terminal ownership through the universal registry.
        for owner in terminal_owners(entry):
            public_ref = owner.public_ref
            assessment = retirer.assess(
                root=root, branch=branch, path=wt_path, target=owner.target_branch
            )
            category, detail = stranded_category(entry, residue, assessment)
            label = assessment.reason
            if category == "sweep-ready":
                label = "verified-safe; the next landing on this machine sweeps it"
            elif category in ("locked", "dirty"):
                label = f"worktree is {category} ({detail})"
            if args.fix and category == "sweep-ready":
                preserved = retirer.prune(
                    root=root,
                    branch=branch,
                    path=wt_path,
                    target=owner.target_branch,
                    item_id=public_ref,
                    assessment=assessment,
                    release_branch=owner.branch if detached_head(branch) else "",
                )
                if not preserved:
                    fixed.append(
                        f"- Fixed: removed terminal lane {branch} at {wt_path} — {public_ref}"
                    )
                    continue
                category, label = "preserved", preserved[0]
            stranded.setdefault(category, []).append(
                f"{public_ref}: {detail}" if detail else public_ref
            )
            issues.append(
                f"- Terminal-item lane: {branch} at {wt_path} — {public_ref} is {owner.status}; {label}"
            )

    # An interrupted removal leaves an unregistered tombstone; --fix finishes it.
    if repo_root:
        leftovers = tombstones(repo_root)
        results = finish_tombstones(repo_root) if args.fix else []
        for leftover, result in zip(leftovers, results):
            if result.removed and not result.reason:
                fixed.append(f"- Fixed: finished interrupted removal {leftover}")
            else:
                issues.append(f"- Interrupted removal not finished: {result.reason}")
        for leftover in leftovers[len(results) :]:
            issues.append(
                f"- Interrupted removal left tombstone {leftover}; --fix finishes it"
            )

    # Self-deploy driver trees, answered from their run's status rather than
    # from an owning item. Without --fix nothing here touches the tree; a run
    # still going is not reported at all, because its pin is in use.
    if repo_root:
        sweep = (
            retire_terminal_deploy_run_worktrees
            if args.fix
            else assess_deploy_run_worktrees
        )
        for lane in sweep(
            repo_root=str(repo_root), run_git=_git_for_repo(str(repo_root))
        ):
            if lane.retired:
                fixed.append(
                    f"- Fixed: retired finished deploy-run worktree "
                    f"{lane.path} — {lane.run_id}"
                )
                continue
            if lane.run_is_open:
                continue
            stranded.setdefault(DEPLOY_RUN_CATEGORY, []).append(lane.run_id)
            issues.append(
                f"- Finished deploy-run worktree: {lane.path} — {lane.run_id}; "
                + (lane.reason or _DEPLOY_RUN_RETIRABLE_LABEL)
            )

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
                for owner in by_path.get(child_str, []):
                    if owner.status in _TERMINAL:
                        stranded.setdefault("unregistered directory", []).append(
                            owner.public_ref
                        )
                        issues.append(
                            f"- Stale worktree directory: {child_str} "
                            f"— {owner.public_ref} is {owner.status} "
                            "(unregistered directory preserved for inspection)"
                        )

    for lane in stale_branches:
        branch = lane.branch
        assessment = retirer.assess(
            root=str(repo_root),
            branch=branch,
            path=lane.path,
            target=lane.target_branch,
        )
        if args.fix and assessment.safe:
            preserved = retirer.prune(
                root=str(repo_root),
                branch=branch,
                path=lane.path,
                target=lane.target_branch,
                item_id=lane.public_ref,
                assessment=assessment,
            )
            if not preserved:
                fixed.append(f"- Fixed: deleted terminal local branch {branch}")
                continue
        issues.append(
            f"- Stale local branch: {branch} — {lane.public_ref}; "
            f"{assessment.reason or 'verified-safe'}"
        )

    # Terminal updates release operational lanes but retain audit history.
    for lane in lanes:
        if lane.status in _TERMINAL and lane.state == "active":
            issues.append(
                f"- Active worktree lane on terminal item: {lane.public_ref} "
                f"has branch='{lane.branch}' "
                "(release the lane while preserving its audit record)"
            )

    if stranded:
        issues.insert(0, stranded_summary(stranded))
    if issues:
        detail = [*fixed, *issues]
        rec.record("HC-worktree-health", "Worktree health", "WARN", "\n".join(detail))
    elif fixed:
        rec.record("HC-worktree-health", "Worktree health", "PASS", "\n".join(fixed))
    else:
        rec.record("HC-worktree-health", "Worktree health", "PASS", "")
