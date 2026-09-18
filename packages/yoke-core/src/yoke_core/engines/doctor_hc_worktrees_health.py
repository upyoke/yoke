"""Worktree health check — uncommitted, stale, and stranded lanes.

Cluster: HC-worktree-health (single HC). Inspects ``git worktree list``,
the configured ``.worktrees`` directory, local item branches, and the
universal ``item_worktrees`` registry. A lane whose item is terminal but
which is still on disk is reported with the reason it survived — the same
proofs the landing cleanup and the merged-lane sweep apply — rolled up on
one line ("N released lanes still on disk: dirty (...), locked (...),
unregistered directory (...)") ahead of the per-lane detail, so an operator
sees what needs a decision before reading the list.

Both halves of that answer must run on the machine holding the checkout,
because only it can see the lanes. The control-plane half therefore reads
through the registered relayed surface — ``item_worktrees.inventory`` for
lane ownership and ``merge.prune.authority_verdict`` for the idle-authority
proof — never local SQL. A project that relays to a control plane over
https has a checkout but no local database, so a SQL-reading version of
this check could never run for a hosted or external project at all, and
their released lanes accumulated unseen. A control plane that cannot serve
those reads is reported N/A with that reason, never as a pass or a failure
about the project.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from yoke_core.domain.control_plane_transport import relay
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


def _git_for_repo(repo_root: str):
    def run(command, *, cwd=None, capture=True):
        return _base._run(["git", "-C", repo_root, *command])

    return run


class _Lane:
    """One control-plane lane row, as this check consumes it."""

    __slots__ = (
        "item_id",
        "public_ref",
        "status",
        "branch",
        "path",
        "state",
        "target_branch",
    )

    def __init__(self, row: Dict[str, object]) -> None:
        self.item_id = int(row.get("item_id") or 0)
        self.public_ref = str(row.get("public_ref") or "")
        self.status = str(row.get("status") or "")
        self.branch = str(row.get("branch") or "")
        self.path = str(row.get("path") or "")
        self.state = str(row.get("state") or "")
        self.target_branch = str(row.get("target_branch") or "main")


def _lane_inventory(project: str) -> List[_Lane] | None:
    """Every registered lane for *project*, or None when unreadable.

    None is the honest "cannot answer" that becomes an N/A, never an empty
    inventory: a caller that read zero lanes from an unreachable control
    plane would conclude the machine has nothing to retire.
    """
    try:
        result = relay("item_worktrees.inventory", {"project": str(project)})
    except Exception:  # noqa: BLE001 - unreachable authority == cannot answer
        return None
    rows = result.get("lanes")
    if not isinstance(rows, list):
        return None
    return [_Lane(row) for row in rows if isinstance(row, dict)]


def _authority_block(branch: str, path: str) -> str:
    """Why cleanup authority forbids pruning this lane, or empty when idle."""
    payload: Dict[str, object] = {"branch": branch}
    if path:
        payload["path"] = path
    try:
        verdict = relay("merge.prune.authority_verdict", payload)
    except Exception:  # noqa: BLE001 - fail closed: unprovable == still held
        return "cleanup authority is active or unreadable"
    if verdict.get("prunable"):
        return ""
    reason = str(verdict.get("reason") or "")
    if reason == "active_authority":
        return "cleanup authority is active or unreadable"
    return f"no unique terminal owner ({reason or 'unproven'})"


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
    """HC-worktree-health: Worktree health.

    Takes the runner's connection positionally and never uses it: every
    control-plane fact here arrives over the relayed surface, which is what
    lets the check run on any machine holding the checkout.
    """
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

    lanes = _lane_inventory(args.project)
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
    by_branch: Dict[str, List[_Lane]] = {}
    by_path: Dict[str, List[_Lane]] = {}
    for lane in lanes:
        by_branch.setdefault(lane.branch, []).append(lane)
        if lane.path:
            by_path.setdefault(lane.path, []).append(lane)

    for entry in entries:
        wt_path = entry.get("path", "")
        branch = entry.get("branch", "")
        if branch in ("main", "master") or not wt_path:
            continue
        root = str(repo_root or Path(wt_path).parents[1])

        # Named or project-declared ignored caches are disposable; anything
        # else is lane content.
        residue = None
        if Path(wt_path).is_dir():
            residue = assess_lane_residue(
                _git_for_repo(root), wt_path, declared_disposable_roots(root)
            )
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
                authority_block=_authority_block(branch, wt_path),
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

    # Detect stale local branches for done/cancelled items
    live_branches = {entry.get("branch", "") for entry in entries}
    for lane in lanes:
        if lane.status not in _TERMINAL:
            continue
        branch = lane.branch
        br = _base._run(["git", "rev-parse", "--verify", branch])
        if repo_root and br.returncode == 0 and branch not in live_branches:
            assessment = assess_landed_lane(
                repo_root=str(repo_root),
                branch=branch,
                target=lane.target_branch,
                run_git=_git_for_repo(str(repo_root)),
                refresh_target=False,
                authority_block=_authority_block(branch, lane.path),
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
