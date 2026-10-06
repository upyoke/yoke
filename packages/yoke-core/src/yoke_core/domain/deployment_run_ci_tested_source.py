"""The commit a CI-gated release binds: one that has its own CI run.

A stage that waits for CI passes only when the project's ``ci_workflow_file``
has a passing run whose head is exactly the release commit, and a merge-queue
push runs CI only on its newest commit. So ``deployment_runs.create`` with no
source binds the newest gate-branch commit whose own run passed or is
running, or — when none has one, as for CI that never runs on push —
dispatches the workflow on the branch and binds the commit that run tests.
Every path that binds an explicit commit refuses one without its own run.
Flows without a CI wait, projects without a CI workflow, and ephemeral
candidates are untouched; the gate itself is unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
)

# How far back along the gate branch creation looks for a tested commit.
COMMIT_WINDOW = 100
_TESTED_STATES = frozenset({"passed", "running"})
_FULL_SHA = re.compile(r"[0-9a-f]{40}")
UNTESTED = "release_source_untested"
UNVERIFIABLE = "release_source_unverifiable"


class ReleaseSourceRefused(Exception):
    """A release source the CI gate could never pass, refused before binding."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CiGateTarget:
    """The repository, workflow, and branch one release's CI gate reads."""

    project: str
    flow: str
    repo: str
    workflow: str
    branch: str
    token: str


def _waits_for_ci(stage: Any) -> bool:
    return (
        isinstance(stage, dict)
        and stage.get("step_runner") == "github-actions-workflow"
        and stage.get("wait_for_ci", True) is not False
    )


def _flow_facts(
    flow: str, environment: Optional[str]
) -> Optional[tuple[list, str, str]]:
    """Return the flow's stages, tier, and gate environment name.

    ``None`` for an unknown flow: run creation refuses that by name itself.
    """
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.json_helper import loads_text

    conn = connect(None)
    try:
        row = conn.execute(
            "SELECT stages, target_tier, target_environment_id "
            "FROM deployment_flows WHERE id = %s",
            (flow,),
        ).fetchone()
        if row is None:
            return None
        stages = loads_text(row[0]) if row[0] else []
        tier = str(row[1] or "")
        env_name = (environment or "").strip()
        if env_name:
            tier = "persistent"
        elif row[2] is not None:
            env_row = conn.execute(
                "SELECT name FROM environments WHERE id = %s", (row[2],)
            ).fetchone()
            env_name = str(env_row[0]) if env_row else ""
        return list(stages or []), tier, env_name
    finally:
        conn.close()


def _auth(project: str, flow: str, permissions: Mapping[str, str]) -> Any:
    from yoke_core.domain.project_github_auth import (
        ProjectGithubAuthError,
        repair_command_hint,
        resolve_project_github_auth,
    )

    try:
        return resolve_project_github_auth(project, required_permissions=permissions)
    except ProjectGithubAuthError as exc:
        raise ReleaseSourceRefused(
            UNVERIFIABLE,
            f"flow '{flow}' waits for CI, but project '{project}' GitHub "
            f"auth cannot reach its CI runs: {exc.code}: {exc}\n"
            f"  Repair: {repair_command_hint(exc, project)}",
        ) from exc


def ci_gate_target(
    project: str, flow: str, environment: Optional[str]
) -> Optional[CiGateTarget]:
    """Return what the flow's CI gate reads, or ``None`` when it reads nothing."""
    from yoke_core.domain.deploy_pipeline_gates import resolve_flow_gate_branch
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_slug,
    )
    from yoke_core.domain.project_renderer_settings import (
        project_ci_workflow_file,
    )

    facts = _flow_facts(flow, environment)
    if facts is None:
        return None
    stages, tier, env_name = facts
    if not any(_waits_for_ci(stage) for stage in stages):
        return None
    workflow = project_ci_workflow_file(project)
    if not workflow:
        return None
    checkout = checkout_for_project_slug(project)
    branch = resolve_flow_gate_branch(
        project, tier, env_name, str(checkout) if checkout is not None else ""
    )
    if not branch:
        return None
    auth = _auth(project, flow, GITHUB_ACTIONS_READ_PERMISSION_LEVELS)
    return CiGateTarget(project, flow, auth.repo, workflow, branch, auth.token)


def _read(target: CiGateTarget, path: str, query: Dict[str, str]) -> Any:
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_get

    try:
        data = rest_get(path, query=query, token=target.token)
    except RestTransportError as exc:
        raise ReleaseSourceRefused(
            UNVERIFIABLE,
            f"could not read {path} in {target.repo} to find a CI-tested "
            f"release commit: {exc}. Retry the create; nothing was created.",
        ) from exc
    if data is None:
        raise ReleaseSourceRefused(
            UNVERIFIABLE,
            f"{target.repo} has no {path}: confirm the project's "
            f"ci_workflow_file ({target.workflow}) and branch "
            f"({target.branch}) exist. Nothing was created.",
        )
    return data


def _newest_run_by_commit(
    target: CiGateTarget, query: Dict[str, str]
) -> Dict[str, dict]:
    from yoke_core.domain.github_actions_rest import newest_run

    data = _read(
        target,
        f"/repos/{target.repo}/actions/workflows/{target.workflow}/runs",
        {"branch": target.branch, "per_page": str(COMMIT_WINDOW), **query},
    )
    runs = data.get("workflow_runs") if isinstance(data, dict) else None
    grouped: Dict[str, List[dict]] = {}
    for run in runs if isinstance(runs, list) else []:
        if isinstance(run, dict) and run.get("head_sha"):
            grouped.setdefault(str(run["head_sha"]), []).append(run)
    return {sha: newest_run(group) for sha, group in grouped.items()}


def _state(run: Optional[dict]) -> str:
    from yoke_core.domain.handlers.github_actions_check_ci import _classify

    return _classify(run).state


def newest_tested_commit(target: CiGateTarget) -> str:
    """The newest gate-branch commit whose own CI run passed or is running."""
    runs = _newest_run_by_commit(target, {})
    commits = _read(
        target,
        f"/repos/{target.repo}/commits",
        {"sha": target.branch, "per_page": str(COMMIT_WINDOW)},
    )
    for commit in commits if isinstance(commits, list) else []:
        sha = str(commit.get("sha") or "") if isinstance(commit, dict) else ""
        if _state(runs.get(sha)) in _TESTED_STATES:
            return sha
    return ""


def dispatch_branch_ci(target: CiGateTarget) -> str:
    """Start the CI workflow on the gate branch; return the commit it tests."""
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_post

    auth = _auth(target.project, target.flow, GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS)
    path = f"/repos/{target.repo}/actions/workflows/{target.workflow}/dispatches"
    recovery = (
        f"  Recovery: start {target.workflow} on {target.branch} by hand, "
        "then create the run again without --source-ref. Nothing was created."
    )
    try:
        result = rest_post(
            path,
            body={"ref": target.branch, "return_run_details": True},
            token=auth.token,
            max_attempts=1,
        )
    except RestTransportError as exc:
        raise ReleaseSourceRefused(
            UNVERIFIABLE,
            f"no commit on {target.repo}@{target.branch} has its own "
            f"{target.workflow} run, and dispatching one failed: {exc}\n{recovery}",
        ) from exc
    run_id = result.get("workflow_run_id") if isinstance(result, dict) else None
    run = (
        _read(target, f"/repos/{target.repo}/actions/runs/{run_id}", {})
        if run_id
        else None
    )
    sha = str(run.get("head_sha") or "") if isinstance(run, dict) else ""
    if not _FULL_SHA.fullmatch(sha):
        raise ReleaseSourceRefused(
            UNVERIFIABLE,
            f"dispatched {target.workflow} on {target.repo}@{target.branch}, "
            "but GitHub named no run and commit for it, so no release commit "
            f"can be bound to that run.\n{recovery}",
        )
    return sha


def _untested(
    target: CiGateTarget, lineage: str, state: str, retry: bool
) -> ReleaseSourceRefused:
    newest = newest_tested_commit(target)
    if retry:
        how = (
            "a retry keeps its candidate, so create a new run instead (no "
            "--retry-of): without --source-ref it binds a tested commit."
        )
    elif newest:
        how = f"omit --source-ref to bind {newest}, or pass --source-ref {newest}."
    else:
        how = (
            f"omit --source-ref: creation then dispatches {target.workflow} "
            f"on {target.branch} and binds the commit that run tests."
        )
    tested = (
        f" The newest commit with its own passing or running run is {newest}."
        if newest
        else ""
    )
    finding = (
        "has no run of its own" if state == "no_runs" else f"has run state {state}"
    )
    return ReleaseSourceRefused(
        UNTESTED,
        f"release commit {lineage} {finding} in {target.workflow} on "
        f"{target.repo}@{target.branch}, so flow '{target.flow}' would block "
        f"at its CI gate. Nothing was bound.{tested}\n  Recovery: {how}",
    )


def require_tested_lineage(
    project: str,
    flow: str,
    environment: Optional[str],
    release_lineage: Optional[str],
    *,
    retry: bool = False,
) -> None:
    """Refuse an explicit commit the flow's CI gate could never pass."""
    lineage = (release_lineage or "").strip()
    if not _FULL_SHA.fullmatch(lineage):
        # Empty is settled by the caller; an annotated release tag is peeled
        # at execution, where the gate reads the peeled commit's own run.
        return
    target = ci_gate_target(project, flow, environment)
    if target is None:
        return
    own = _newest_run_by_commit(target, {"head_sha": lineage}).get(lineage)
    state = _state(own)
    if state not in _TESTED_STATES:
        raise _untested(target, lineage, state, retry)


def bind_tested_release_source(
    project: str,
    flow: str,
    environment: Optional[str],
    release_lineage: Optional[str],
    *,
    retry: bool = False,
) -> Optional[str]:
    """Return the lineage to create the run with, or refuse by name."""
    if (release_lineage or "").strip():
        require_tested_lineage(project, flow, environment, release_lineage, retry=retry)
        return release_lineage
    target = ci_gate_target(project, flow, environment)
    if target is None:
        return release_lineage
    return newest_tested_commit(target) or dispatch_branch_ci(target)


def tested_lineage_refusal(conn: Any, run_id: str, value: str) -> Optional[str]:
    """Name why an existing run may not bind *value*, or ``None``."""
    row = conn.execute(
        "SELECT r.flow, p.slug, e.name FROM deployment_runs r "
        "JOIN projects p ON p.id = r.project_id "
        "LEFT JOIN environments e ON e.id = r.target_environment_id "
        "WHERE r.id = %s",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        require_tested_lineage(str(row[1]), str(row[0]), row[2], value)
    except ReleaseSourceRefused as exc:
        return f"Error: {exc.code}: {exc}"
    return None


__all__ = [
    "COMMIT_WINDOW",
    "CiGateTarget",
    "ReleaseSourceRefused",
    "UNTESTED",
    "UNVERIFIABLE",
    "bind_tested_release_source",
    "ci_gate_target",
    "dispatch_branch_ci",
    "newest_tested_commit",
    "require_tested_lineage",
    "tested_lineage_refusal",
]
