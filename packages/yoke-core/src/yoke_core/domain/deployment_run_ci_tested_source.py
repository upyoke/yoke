"""The commit a CI-gated release binds: one that has its own CI run.

A flow stage that waits for CI passes only when the project's declared
``ci_workflow_file`` has a passing run whose head is exactly the release
commit. A merge-queue push lands several commits on the gate branch at once
and only the newest gets its own push run, so an earlier commit of that push
can never pass the gate, and no dispatch can fix it: GitHub runs a workflow
from a ref, which tests whatever the ref points at by then.

So ``deployment_runs.create`` settles the commit before minting a run ID.
With no source given, it binds the newest commit on the gate branch whose
own run passed or is still running. An explicit commit without such a run is
refused with the newest commit that has one. Flows that do not wait for CI,
projects that declare no CI workflow, and ephemeral candidates (no gate
branch) are untouched. The gate itself is unchanged: it still requires a
passing run at the exact release commit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)

# How far back along the gate branch creation looks for a tested commit.
COMMIT_WINDOW = 100
_TESTED_STATES = frozenset({"passed", "running"})
_FULL_SHA = re.compile(r"[0-9a-f]{40}")


class ReleaseSourceRefused(Exception):
    """A release source the CI gate could never pass, refused before a run ID."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CiGateTarget:
    """The repository, workflow, and branch one release's CI gate reads."""

    project: str
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
) -> Optional[tuple[list, str, str, int]]:
    """Return the flow's stages, tier, gate environment name, and project id.

    ``None`` for an unknown flow: run creation refuses that by name itself.
    """
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.json_helper import loads_text

    conn = connect(None)
    try:
        row = conn.execute(
            "SELECT stages, target_tier, target_environment_id, project_id "
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
        return list(stages or []), tier, env_name, int(row[3])
    finally:
        conn.close()


def _gate_branch(project: str, project_id: int, tier: str, env_name: str) -> str:
    """The branch the CI gate filters by — the same rule the gate resolves."""
    from yoke_contracts.deployment_flow_target_tier import TARGET_TIER_EPHEMERAL
    from yoke_core.domain import project_settings
    from yoke_core.domain.deploy_environment_settings import declared_env_branch

    if tier == TARGET_TIER_EPHEMERAL:
        return ""
    declared = declared_env_branch(project, env_name) if env_name else ""
    return declared or project_settings.get_project_str_for_id(
        project_id, "base_branch"
    )


def ci_gate_target(
    project: str, flow: str, environment: Optional[str]
) -> Optional[CiGateTarget]:
    """Return what the flow's CI gate reads, or ``None`` when it reads nothing."""
    from yoke_core.domain.project_github_auth import (
        ProjectGithubAuthError,
        repair_command_hint,
        resolve_project_github_auth,
    )
    from yoke_core.domain.project_renderer_settings import (
        project_ci_workflow_file,
    )

    facts = _flow_facts(flow, environment)
    if facts is None:
        return None
    stages, tier, env_name, project_id = facts
    if not any(_waits_for_ci(stage) for stage in stages):
        return None
    workflow = project_ci_workflow_file(project)
    branch = _gate_branch(project, project_id, tier, env_name)
    if not workflow or not branch:
        return None
    try:
        auth = resolve_project_github_auth(
            project, required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS
        )
    except ProjectGithubAuthError as exc:
        raise ReleaseSourceRefused(
            "release_source_unverifiable",
            f"flow '{flow}' waits for CI, but project '{project}' GitHub "
            f"auth cannot read its CI runs: {exc.code}: {exc}\n"
            f"  Repair: {repair_command_hint(exc, project)}",
        ) from exc
    return CiGateTarget(project, auth.repo, workflow, branch, auth.token)


def _read(target: CiGateTarget, path: str, query: Dict[str, str]) -> Any:
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_get

    try:
        data = rest_get(path, query=query, token=target.token)
    except RestTransportError as exc:
        raise ReleaseSourceRefused(
            "release_source_unverifiable",
            f"could not read {path} in {target.repo} to find a CI-tested "
            f"release commit: {exc}. Retry the create; nothing was created.",
        ) from exc
    if data is None:
        raise ReleaseSourceRefused(
            "release_source_unverifiable",
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


def _no_tested_commit(target: CiGateTarget) -> ReleaseSourceRefused:
    return ReleaseSourceRefused(
        "release_source_untested",
        f"none of the newest {COMMIT_WINDOW} commits on {target.repo}@"
        f"{target.branch} has its own passing or running {target.workflow} "
        "run, so the CI gate could not pass any of them. Nothing was "
        f"created.\n  Recovery: land or re-run {target.workflow} on "
        f"{target.branch}, then create the run again.",
    )


def bind_tested_release_source(
    project: str,
    flow: str,
    environment: Optional[str],
    release_lineage: Optional[str],
) -> Optional[str]:
    """Return the lineage to create the run with, or refuse by name."""
    target = ci_gate_target(project, flow, environment)
    if target is None:
        return release_lineage
    lineage = (release_lineage or "").strip()
    if not lineage:
        newest = newest_tested_commit(target)
        if not newest:
            raise _no_tested_commit(target)
        return newest
    if not _FULL_SHA.fullmatch(lineage):
        # An annotated release tag is peeled at execution, where the gate
        # reads the peeled commit's own run.
        return lineage
    own = _newest_run_by_commit(target, {"head_sha": lineage}).get(lineage)
    state = _state(own)
    if state in _TESTED_STATES:
        return lineage
    newest = newest_tested_commit(target)
    suggestion = (
        f"  Recovery: create the run on {newest}, the newest commit on "
        f"{target.branch} with its own passing or running run — omit "
        f"--source-ref to bind it, or pass --source-ref {newest}."
        if newest
        else f"  Recovery: land or re-run {target.workflow} on "
        f"{target.branch}, then create the run again."
    )
    finding = (
        "has no run of its own" if state == "no_runs" else f"has run state {state}"
    )
    raise ReleaseSourceRefused(
        "release_source_untested",
        f"release commit {lineage} {finding} in {target.workflow} on "
        f"{target.repo}@{target.branch}, so flow '{flow}' would block at "
        f"its CI gate. Nothing was created.\n{suggestion}",
    )


__all__ = [
    "COMMIT_WINDOW",
    "CiGateTarget",
    "ReleaseSourceRefused",
    "bind_tested_release_source",
    "ci_gate_target",
    "newest_tested_commit",
]
