"""Path-claim boundary proved from the merge an item landed.

Before landing, the boundary is the lane's committed diff against the
moving integration target. After landing that question has a fixed answer:
the merge commit's diff against its first parent is exactly what the item
put on the target, and it never goes stale when the target moves on. So a
gate evaluated after the landing proves the boundary from that merge, with
no lane and no current remote head required.

The landing applies while it still describes the item's current work: the
newest recorded landing, unless an active lane has since recorded a head
that is neither the landed candidate nor the merge (rework that has not
landed yet, which the lane-based check owns).

The diff is read from git when a checkout on this machine holds the merge
commit, and otherwise from the project's GitHub capability, which is how a
hosted control plane without checkouts answers it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple
from urllib.parse import quote

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain import db_backend
from yoke_core.domain.gate_satisfier_facts import OBSERVED_LANDED_MERGE
from yoke_core.domain.gate_satisfier_ladder import LadderResolution
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    PATH_CLAIM_BOUNDARY_LADDER,
)
from yoke_core.domain.gate_satisfier_stamp import record_rung
from yoke_core.domain.item_landings import ItemLanding, landings_for_item
from yoke_core.domain.item_worktrees import primary_item_worktree
from yoke_core.domain.path_claims import get_claim
from yoke_core.domain.path_claims_boundary_git import (
    BoundaryCheckError,
    collect_committed_changes,
    run_git,
)
from yoke_core.domain.path_claims_boundary_targets import path_strings_for_target_ids
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _table_exists

#: GitHub's compare endpoint lists at most this many changed files.
GITHUB_COMPARE_FILE_LIMIT = 300
LANDED_MERGE_RUNG = "landed_merge"


class LandedBoundaryUnprovable(RuntimeError):
    """The landed merge's diff could not be read from any source."""


def landing_for_boundary(conn: Any, item_id: int) -> Optional[ItemLanding]:
    """The landing that answers this item's boundary, or ``None`` before one.

    A database that has not converged ``item_landings`` has recorded no
    landing either, so it takes the lane-based check rather than failing.
    """
    if not _table_exists(conn, "item_landings"):
        return None
    landings = landings_for_item(conn, item_id)
    if not landings:
        return None
    newest = landings[-1]
    lane = primary_item_worktree(conn, item_id) or {}
    head = str(lane.get("commit_sha") or "")
    if head and head not in (newest.candidate_sha, newest.merge_sha):
        return None
    return newest


def _commit_present(repo_path: str, sha: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", repo_path, "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def _diff_from_git(
    repo_path: str, merge_sha: str
) -> Tuple[str, List[str], List[Tuple[str, str]]]:
    parent = run_git(repo_path, "rev-parse", f"{merge_sha}^1").strip()
    touched, renames = collect_committed_changes(
        repo_path, base_sha=parent, head_sha=merge_sha
    )
    return parent, touched, renames


def _diff_from_github(
    conn: Any, project_slug: str, merge_sha: str
) -> Optional[Tuple[str, List[str], List[Tuple[str, str]]]]:
    from yoke_core.domain.github_actions_rest import rest_get
    from yoke_core.domain.project_github_auth import (
        MissingCapability,
        ProjectGithubAuthError,
        resolve_project_github_auth,
    )

    try:
        auth = resolve_project_github_auth(
            project_slug,
            conn=conn,
            required_permissions=GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
        )
    except MissingCapability:
        return None
    except ProjectGithubAuthError as exc:
        raise LandedBoundaryUnprovable(
            f"the project's GitHub capability is unusable: {exc.code}: {exc}"
        ) from exc
    try:
        commit = rest_get(f"/repos/{auth.repo}/commits/{merge_sha}", token=auth.token)
        parents = (commit or {}).get("parents") or []
        if not parents:
            raise LandedBoundaryUnprovable(
                f"GitHub has no parent for merge {merge_sha} in {auth.repo}"
            )
        parent = str(parents[0].get("sha") or "")
        compare = rest_get(
            f"/repos/{auth.repo}/compare/{quote(parent)}...{quote(merge_sha)}",
            token=auth.token,
        )
    except LandedBoundaryUnprovable:
        raise
    except Exception as exc:
        raise LandedBoundaryUnprovable(
            f"GitHub could not read merge {merge_sha}: {type(exc).__name__}: {exc}"
        ) from exc
    if compare is None:
        raise LandedBoundaryUnprovable(
            f"GitHub cannot compare {parent}...{merge_sha} in {auth.repo}"
        )
    files = list(compare.get("files") or [])
    if len(files) >= GITHUB_COMPARE_FILE_LIMIT:
        raise LandedBoundaryUnprovable(
            f"merge {merge_sha} changes {len(files)} or more files, past the "
            f"{GITHUB_COMPARE_FILE_LIMIT}-file list GitHub returns; rerun the "
            "close-out on a machine whose project checkout has fetched the merge"
        )
    touched = list(dict.fromkeys(str(f.get("filename") or "") for f in files))
    renames = [
        (str(f["previous_filename"]), str(f.get("filename") or ""))
        for f in files
        if f.get("status") == "renamed" and f.get("previous_filename")
    ]
    return parent, [path for path in touched if path], renames


def _local_checkouts(conn: Any, item_id: int, project_id: int) -> List[str]:
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_id,
        item_worktree_path,
    )

    candidates = [
        item_worktree_path(conn, item_id),
        checkout_for_project_id(project_id),
    ]
    return [
        str(path) for path in candidates if path is not None and Path(path).is_dir()
    ]


def landed_merge_diff(
    conn: Any, *, item_id: int, project_id: int, project_slug: str, merge_sha: str
) -> Tuple[str, str, List[str], List[Tuple[str, str]]]:
    """Return ``(source, first_parent, touched_paths, rename_pairs)``."""
    for repo_path in _local_checkouts(conn, item_id, project_id):
        if _commit_present(repo_path, merge_sha):
            try:
                return ("git", *_diff_from_git(repo_path, merge_sha))
            except BoundaryCheckError as exc:
                raise LandedBoundaryUnprovable(str(exc)) from exc
    remote = _diff_from_github(conn, project_slug, merge_sha)
    if remote is None:
        raise LandedBoundaryUnprovable(
            f"no checkout on this machine holds merge {merge_sha} and the "
            "project declares no GitHub capability to read it from; fetch the "
            "integration target in the project checkout and retry"
        )
    return ("github", *remote)


def _declared_coverage(conn: Any, claim_ids: Sequence[int]) -> Tuple[set, set]:
    declared: set = set()
    targets: set = set()
    for claim_id in claim_ids:
        claim = get_claim(conn, claim_id)
        targets.add(str(claim.get("integration_target") or ""))
        ids = [int(tid) for tid in claim.get("target_ids") or []]
        declared.update(path_strings_for_target_ids(conn, ids))
    return declared, targets


def _blocked(message: str) -> dict:
    return {
        "success": False,
        "error_code": "GATE_PATH_CLAIM_BOUNDARY",
        "error": message,
    }


def check_landed_boundary(
    conn: Any,
    *,
    item_id: int,
    target_status: str,
    claim_ids: Sequence[int],
    landing: ItemLanding,
) -> Optional[dict]:
    """Prove the boundary from ``landing``; ``None`` clears the gate."""
    ref = render_item_ref(conn, item_id)
    project_id, project_slug = conn.execute(
        "SELECT p.id, p.slug FROM items i JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {'%s' if db_backend.connection_is_postgres(conn) else '?'}",
        (int(item_id),),
    ).fetchone()
    declared, targets = _declared_coverage(conn, claim_ids)
    if landing.target_branch and targets - {landing.target_branch}:
        return _blocked(
            f"{ref} landed merge {landing.merge_sha} on {landing.target_branch!r}, "
            f"but its path claims integrate into {sorted(targets)}; that landing "
            "cannot prove their coverage. Amend the claims' integration target "
            "or land the item on the claimed target, then retry the transition."
        )
    try:
        source, parent, touched, renames = landed_merge_diff(
            conn,
            item_id=item_id,
            project_id=int(project_id),
            project_slug=str(project_slug),
            merge_sha=landing.merge_sha,
        )
    except LandedBoundaryUnprovable as exc:
        return _blocked(
            f"{ref} landed as merge {landing.merge_sha}, but the boundary "
            f"cannot be proved from it: {exc}. Fix that, then re-run the same "
            "close-out or lifecycle transition; the item's lane is not needed."
        )
    undeclared = sorted(set(touched) - declared)
    if undeclared:
        return _blocked(
            f"Path-claim boundary check blocked transition to {target_status!r}: "
            f"landed merge {landing.merge_sha} (diff against first parent "
            f"{parent}) changed {len(undeclared)} file(s) outside {ref}'s "
            f"declared coverage: {', '.join(undeclared)}.\n\nThe work has "
            "already landed, so widen the claim to cover what landed "
            "(`yoke claims path widen --claim-id N --add-paths ...`), then re-run the same close-out."
        )
    fact = {
        "merge_sha": landing.merge_sha,
        "first_parent_sha": parent,
        "source": source,
        "touched_paths": sorted(touched),
        "rename_pairs": [list(pair) for pair in renames],
    }
    record_rung(
        conn,
        item_id=item_id,
        ladder=PATH_CLAIM_BOUNDARY_LADDER,
        resolution=LadderResolution(
            obligation=PATH_CLAIM_BOUNDARY_LADDER.obligation,
            rung=PATH_CLAIM_BOUNDARY_LADDER.rung(LANDED_MERGE_RUNG),
            facts={OBSERVED_LANDED_MERGE: json.dumps(fact, sort_keys=True)},
        ),
        target_status=target_status,
    )
    return None


__all__ = [
    "GITHUB_COMPARE_FILE_LIMIT",
    "LANDED_MERGE_RUNG",
    "LandedBoundaryUnprovable",
    "check_landed_boundary",
    "landed_merge_diff",
    "landing_for_boundary",
]
