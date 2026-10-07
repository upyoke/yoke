"""Which gate-branch commits a release created without a source may bind.

A release created without ``--source-ref`` binds a commit the CI gate can
pass, and that commit must be a state the gate branch itself held. Only the
branch's first-parent line from its tip qualifies: a second parent is a branch
that was merged in, never a state of the gate branch. Only runs GitHub
recorded for the branch itself count: a merge-queue (``merge_group``) or pull
request run tests a commit that is not, or not yet, on it.

The chosen commit must also carry the release it replaces. A commit that does
not descend from the lineage the previous succeeded run shipped for the same
project and environment would ship a divergence, so creation refuses it by
name — both commits, the run that shipped the older one, and the recovery —
before anything is bound.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from yoke_core.domain.deployment_run_compare_response import CONTAINING_STATUSES

if TYPE_CHECKING:
    from yoke_core.domain.deployment_run_ci_tested_source import CiGateTarget

#: Run events that test a ref other than the gate branch itself.
FOREIGN_REF_EVENTS = frozenset({"merge_group", "pull_request", "pull_request_target"})
OFF_LINEAGE = "release_source_off_lineage"


def runs_by_commit(data: Any, branch: str) -> Dict[str, dict]:
    """Map each commit to the run the CI gate reads among the branch's own runs."""
    from yoke_core.domain.github_actions_rest import newest_run

    runs = data.get("workflow_runs") if isinstance(data, dict) else None
    grouped: Dict[str, List[dict]] = {}
    for run in runs if isinstance(runs, list) else []:
        if (
            isinstance(run, dict)
            and run.get("head_sha")
            and run.get("head_branch") == branch
            and run.get("event") not in FOREIGN_REF_EVENTS
        ):
            grouped.setdefault(str(run["head_sha"]), []).append(run)
    return {sha: newest_run(group) for sha, group in grouped.items()}


def first_parent_line(commits: Any) -> List[str]:
    """The branch tip, then each first parent, as far as *commits* reaches.

    *commits* is GitHub's listing for the branch, tip first; it interleaves
    merged-in commits by date, so the line is walked by parent, not by order.
    """
    listed = [
        entry
        for entry in (commits if isinstance(commits, list) else [])
        if isinstance(entry, dict) and entry.get("sha")
    ]
    by_sha = {str(entry["sha"]): entry for entry in listed}
    line: List[str] = []
    sha = str(listed[0]["sha"]) if listed else ""
    while sha in by_sha and sha not in line:
        line.append(sha)
        parents = by_sha[sha].get("parents")
        first = parents[0] if isinstance(parents, list) and parents else None
        sha = str(first.get("sha") or "") if isinstance(first, dict) else ""
    return line


def previous_release(project: str, environment: str) -> Optional[Tuple[str, str]]:
    """The newest succeeded run's id and lineage for one project and environment.

    The same predecessor carried work compares a new run against.
    """
    from yoke_core.domain.db_helpers import connect

    conn = connect(None)
    try:
        row = conn.execute(
            "SELECT r.id, r.release_lineage FROM deployment_runs r "
            "JOIN projects p ON p.id = r.project_id "
            "LEFT JOIN environments e ON e.id = r.target_environment_id "
            "WHERE p.slug = %s AND r.status = 'succeeded' "
            "AND e.name IS NOT DISTINCT FROM %s "
            "ORDER BY r.completed_at DESC NULLS LAST, r.created_at DESC, "
            "r.id DESC LIMIT 1",
            (project, environment or None),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return str(row[0]), str(row[1] or "").strip()


def _compare_status(target: "CiGateTarget", base: str, head: str) -> str:
    from yoke_core.domain.deployment_run_ci_gate_github import read_refusal
    from yoke_core.domain.deployment_run_ci_tested_source import (
        UNVERIFIABLE,
        ReleaseSourceRefused,
    )
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_get

    path = f"/repos/{target.repo}/compare/{base}...{head}"
    try:
        body = rest_get(path, query={"per_page": "1"}, token=target.token)
    except RestTransportError as exc:
        purpose = (
            f"to confirm release commit {head} carries the previous release {base}"
        )
        raise read_refusal(target, path, exc, purpose) from exc
    status = body.get("status") if isinstance(body, dict) else None
    if not isinstance(status, str) or not status:
        raise ReleaseSourceRefused(
            UNVERIFIABLE,
            f"{target.repo} gave no comparison of the previous release {base} "
            f"with release commit {head}, so creation cannot confirm one "
            "carries the other. Nothing was created.\n  Recovery: confirm "
            f"{base} exists in {target.repo}, then create again.",
        )
    return status


def require_descends_from_previous_release(target: "CiGateTarget", commit: str) -> None:
    """Refuse a selected commit that does not carry the previous release."""
    from yoke_core.domain.deployment_run_ci_tested_source import ReleaseSourceRefused

    previous = previous_release(target.project, target.environment)
    if previous is None:
        return
    run_id, lineage = previous
    if not lineage or lineage == commit:
        return
    status = _compare_status(target, lineage, commit)
    if status in CONTAINING_STATUSES:
        return
    where = f" in {target.environment}" if target.environment else ""
    raise ReleaseSourceRefused(
        OFF_LINEAGE,
        f"selected release commit {commit} on {target.repo}@{target.branch} "
        f"does not descend from {lineage}, the lineage {run_id} last shipped "
        f"for {target.project}{where} (GitHub compares them as {status}), so "
        "this release would ship a divergence. Nothing was bound.\n"
        "  Recovery: create with --project-repo-path CHECKOUT --source-ref "
        f"COMMIT naming a tested commit that descends from {lineage}; if "
        f"{lineage} is itself off {target.branch}, correct {run_id}'s lineage "
        "first.",
    )


__all__ = [
    "FOREIGN_REF_EVENTS",
    "OFF_LINEAGE",
    "first_parent_line",
    "previous_release",
    "require_descends_from_previous_release",
    "runs_by_commit",
]
