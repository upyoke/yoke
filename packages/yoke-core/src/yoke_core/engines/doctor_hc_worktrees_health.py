"""Worktree health check — uncommitted, stale, and stranded lanes.

HC-worktree-health inspects every worktree, local branch and item lane.
The ``item_worktrees`` registry supplies ownership. Terminal lanes still on
disk report the cleanup proof that preserved them, with an operator-first
summary ahead of each lane's detail.

Lane reads run on the checkout machine, with ownership served through
``doctor_worktree_lane_authority``. Unreadable ownership reports N/A. Independent
residue reads overlap under the shared deadline; every lane remains checked.

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
from yoke_core.engines.doctor_worktree_lane_authority import (
    LaneRow,
    authority_block,
    lane_inventory,
)
from yoke_core.engines.merge_landed_lane_cleanup import (
    assess_landed_lane,
    prune_landed_lane,
)
from yoke_core.engines.lane_residue_declared_paths import declared_disposable_roots
from yoke_core.engines.merge_worktree_cleanliness import assess_lane_residue

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)
from yoke_core.engines.doctor_tree_scan import list_directory
from yoke_core.engines.doctor_parallel_reads import bounded_read_map

_TERMINAL = ("done", "cancelled")
# Summary order: what needs an operator first, what the next landing sweeps last.
_DEPLOY_RUN_CATEGORY = "finished deploy run"
_DEPLOY_RUN_RETIRABLE_LABEL = (
    "verified-safe; this check's --fix retires it, as does the next landing "
    "on this machine"
)
_STRANDED_ORDER = (
    "dirty",
    _DEPLOY_RUN_CATEGORY,
    "locked",
    "unregistered directory",
    "claimed",
    "unmerged",
    "preserved",
    "sweep-ready",
)


def _git_for_repo(repo_root: str):
    def run(command, *, cwd=None, capture=True):
        return _base._run(["git", "-C", repo_root, *command])

    return run


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
            current["locked"] = (
                line.removeprefix("locked").strip() or "no reason recorded"
            )
        elif line == "" and current:
            entries.append(current)
            current = {}
    return entries


def _stranded_category(entry: dict, residue, assessment) -> tuple[str, str]:
    """Name why a terminal item's lane is still on disk, operator-first."""
    if "locked" in entry:
        return "locked", entry["locked"]
    if residue is not None and not residue.disposable:
        count = len(residue.precious_paths)
        if not count:
            return "preserved", residue.reason
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

    roots = declared_disposable_roots(repo_root) if repo_root else None
    paths = [
        e["path"]
        for e in entries
        if e.get("branch") not in ("main", "master")
        and Path(e["path"]).is_dir()
        and not run_id_for_driver_worktree(
            Path(e["path"]), Path(repo_root or Path(e["path"]).parents[1])
        )
    ]

    def read_residue(path):
        root = str(repo_root or Path(path).parents[1])
        lane_roots = roots if roots is not None else declared_disposable_roots(root)
        return assess_lane_residue(_git_for_repo(root), path, lane_roots)

    residues = dict(zip(paths, bounded_read_map(read_residue, paths)))

    for entry in entries:
        wt_path = entry.get("path", "")
        branch = entry.get("branch", "")
        if branch in ("main", "master") or not wt_path:
            continue
        root = str(repo_root or Path(wt_path).parents[1])
        if run_id_for_driver_worktree(Path(wt_path), Path(root)):
            # Detached deploy drivers are answered from their run status below.
            continue

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
        owners = {
            lane.public_ref: lane
            for lane in [*by_branch.get(branch, []), *by_path.get(wt_path, [])]
        }.values()
        for owner in owners:
            if owner.status not in _TERMINAL:
                continue
            public_ref = owner.public_ref
            assessment = assess_landed_lane(
                repo_root=root,
                branch=branch,
                target=owner.target_branch,
                run_git=_git_for_repo(root),
                refresh_target=False,
                authority_block=authority_block(branch, wt_path),
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
                    target=owner.target_branch,
                    item_id=owner.item_id,
                    run_git=_git_for_repo(root),
                    emit=lambda *_a, **_kw: None,
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
            stranded.setdefault(_DEPLOY_RUN_CATEGORY, []).append(lane.run_id)
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
    for lane in lanes:
        if lane.status not in _TERMINAL:
            continue
        branch = lane.branch
        if repo_root and branch in local_branches and branch not in live_branches:
            assessment = assess_landed_lane(
                repo_root=str(repo_root),
                branch=branch,
                target=lane.target_branch,
                run_git=_git_for_repo(str(repo_root)),
                refresh_target=False,
                authority_block=authority_block(branch, lane.path),
            )
            if args.fix and assessment.safe:
                preserved = prune_landed_lane(
                    repo_root=str(repo_root),
                    branch=branch,
                    target=lane.target_branch,
                    item_id=lane.item_id,
                    run_git=_git_for_repo(str(repo_root)),
                    emit=lambda *_a, **_kw: None,
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
        issues.insert(0, _summary(stranded))
    if issues:
        detail = [*fixed, *issues]
        rec.record("HC-worktree-health", "Worktree health", "WARN", "\n".join(detail))
    elif fixed:
        rec.record("HC-worktree-health", "Worktree health", "PASS", "\n".join(fixed))
    else:
        rec.record("HC-worktree-health", "Worktree health", "PASS", "")
