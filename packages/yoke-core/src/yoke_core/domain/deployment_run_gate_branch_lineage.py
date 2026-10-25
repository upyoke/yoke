"""Where on the gate branch a release created without a source may bind.

A release created without an explicit source binds the gate branch tip, or
the commit tested by a new dispatch on that branch. Which run proves that
commit is :mod:`yoke_core.domain.ci_commit_proof`'s question, not this one.

The chosen commit must also carry the release it replaces. A commit that does
not descend from the lineage the previous succeeded run shipped for the same
project and environment would ship a divergence, so creation refuses it by
name — both commits, the run that shipped the older one, and the recovery —
before anything is bound.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.deployment_run_compare_response import CONTAINING_STATUSES

if TYPE_CHECKING:
    from yoke_core.domain.deployment_run_ci_tested_source import CiGateTarget

OFF_LINEAGE = "release_source_off_lineage"


def gate_branch_tip(target: "CiGateTarget") -> str:
    """Read the current branch tip; an unreadable tip never selects history."""
    from yoke_core.domain.deployment_run_ci_tested_source import (
        _FULL_SHA,
        UNVERIFIABLE,
        ReleaseSourceRefused,
        _read,
    )

    commits = _read(
        target,
        f"/repos/{target.repo}/commits",
        {"sha": target.branch, "per_page": "1"},
    )
    tip = (
        commits[0].get("sha")
        if isinstance(commits, list) and commits and isinstance(commits[0], dict)
        else None
    )
    if isinstance(tip, str) and _FULL_SHA.fullmatch(tip):
        return tip
    raise ReleaseSourceRefused(
        UNVERIFIABLE,
        compose_refusal(
            f"GitHub named no valid tip for {target.repo}@{target.branch}. Nothing was bound.",
            recovery="confirm the gate branch exists and GitHub is readable, then create again.",
        ),
    )


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
            compose_refusal(
                f"{target.repo} gave no comparison of the previous release {base} with release commit {head}, so creation cannot confirm one carries the other. Nothing was created.",
                recovery=f"confirm {base} exists in {target.repo}, then create again.",
            ),
        )
    return status


def require_descends_from_previous_release(
    target: "CiGateTarget", commit: str, source_flag: str
) -> None:
    """Refuse a selected commit that does not carry the previous release.

    *source_flag* is how the calling command names an explicit source.
    """
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
        compose_refusal(
            f"selected release commit {commit} on {target.repo}@{target.branch} does not descend from {lineage}, the lineage {run_id} last shipped for {target.project}{where} (GitHub compares them as {status}), so this release would ship a divergence. Nothing was bound.",
            recovery=f"run the same command with {source_flag} naming a tested commit that descends from {lineage}; if {lineage} is itself off {target.branch}, correct {run_id}'s lineage first.",
        ),
    )


__all__ = [
    "OFF_LINEAGE",
    "gate_branch_tip",
    "previous_release",
    "require_descends_from_previous_release",
]
