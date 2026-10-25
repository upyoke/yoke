"""Bind a release source that its flow's CI gate will pass.

Without a source a release binds the gate branch tip; an explicit commit is
kept. When the flow waits for CI the commit needs its own proof
(:mod:`yoke_core.domain.ci_commit_proof`), from whichever branch started the
run, so merge verification's run on the identical merged commit is reused and
only a tip with no proof gets one dispatch. Proof is not placement: the tip
must descend from the previous release, and composition checks it contains
every member before anything is created.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
)
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.deployment_run_ci_gate_github import (
    CI_GATE_READ_PERMISSIONS,
    read_refusal,
)
from yoke_core.domain.ci_commit_proof import proof_run
from yoke_core.domain.deployment_run_gate_branch_lineage import (
    gate_branch_tip,
    require_descends_from_previous_release,
)
from yoke_core.domain.deployment_run_lineage_requirement import (
    stages_dispatch_a_workflow,
)
from yoke_core.domain.domain_refusal import DomainRefusal

#: Runs read per commit; GitHub's page limit.
RUNS_PER_COMMIT = 100
#: How each command names an explicit release source in its recovery.
CREATE_SOURCE_FLAG = "--source-ref COMMIT --project-repo-path CHECKOUT"
START_SOURCE_FLAG = "--release-lineage COMMIT"
_TESTED_STATES = frozenset({"passed", "running"})
_FULL_SHA = re.compile(r"[0-9a-f]{40}")
UNTESTED = "release_source_untested"
UNVERIFIABLE = "release_source_unverifiable"


class ReleaseSourceRefused(DomainRefusal):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CiGateTarget:
    """Where a dispatching flow's release source is read; ``workflow`` is empty
    when the flow does not wait for CI."""

    project: str
    flow: str
    repo: str
    workflow: str
    branch: str
    token: str
    environment: str = ""


def _waits_for_ci(stage: Any) -> bool:
    return (
        isinstance(stage, dict)
        and stage.get("step_runner") == "github-actions-workflow"
        and stage.get("wait_for_ci", True) is not False
    )


def _flow_facts(
    flow: str, environment: Optional[str]
) -> Optional[tuple[list, str, str]]:
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
            f"flow '{flow}' binds its release source from GitHub, but project "
            f"'{project}' GitHub auth cannot read it: {exc.code}: {exc}\n"
            f"  Repair: {repair_command_hint(exc, project)}",
        ) from exc


def ci_gate_target(
    project: str, flow: str, environment: Optional[str]
) -> Optional[CiGateTarget]:
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
    stages, tier, env = facts
    if not stages_dispatch_a_workflow(stages):
        return None
    waits = any(_waits_for_ci(stage) for stage in stages)
    workflow = project_ci_workflow_file(project) if waits else ""
    checkout = checkout_for_project_slug(project)
    branch = resolve_flow_gate_branch(
        project, tier, env, str(checkout) if checkout is not None else ""
    )
    if not branch:
        return None
    auth = _auth(project, flow, CI_GATE_READ_PERMISSIONS)
    return CiGateTarget(project, flow, auth.repo, workflow, branch, auth.token, env)


def _read(target: CiGateTarget, path: str, query: Dict[str, str]) -> Any:
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_get

    try:
        data = rest_get(path, query=query, token=target.token)
    except RestTransportError as exc:
        purpose = f"in {target.repo} to find a CI-tested release commit"
        raise read_refusal(target, path, exc, purpose) from exc
    if data is None:
        raise ReleaseSourceRefused(
            UNVERIFIABLE,
            f"{target.repo} has no {path}: confirm the project's "
            f"ci_workflow_file ({target.workflow}) and branch "
            f"({target.branch}) exist. Nothing was created.",
        )
    return data


def _proof_state(target: CiGateTarget, sha: str) -> str:
    """The state of the run that proves *sha*, or ``no_runs``."""
    from yoke_core.domain.handlers.github_actions_check_ci import _classify

    data = _read(
        target,
        f"/repos/{target.repo}/actions/workflows/{target.workflow}/runs",
        {"head_sha": sha, "per_page": str(RUNS_PER_COMMIT)},
    )
    runs = data.get("workflow_runs") if isinstance(data, dict) else None
    return _classify(proof_run(runs if isinstance(runs, list) else [], sha)).state


def dispatch_branch_ci(target: CiGateTarget) -> str:
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_post

    auth = _auth(target.project, target.flow, GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS)
    path = f"/repos/{target.repo}/actions/workflows/{target.workflow}/dispatches"
    recovery = (
        f"start {target.workflow} on {target.branch} by hand, then run the "
        "same command again without an explicit source. Nothing was created."
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
            compose_refusal(
                f"the tip of {target.repo}@{target.branch} has no own "
                f"{target.workflow} run, and dispatching one failed: {exc}",
                recovery=recovery,
            ),
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
            compose_refusal(
                f"dispatched {target.workflow} on {target.repo}@{target.branch}, "
                "but GitHub named no run and commit for it, so no release commit "
                "can be bound to that run.",
                recovery=recovery,
            ),
        )
    return sha


def _untested(
    target: CiGateTarget, lineage: str, state: str, retry: bool, source_flag: str
) -> ReleaseSourceRefused:
    tip = f"the {target.branch} tip"
    if retry:
        how = (
            "a retry keeps its candidate, so create a new run instead (no "
            f"--retry-of) and without a source, so it binds {tip}."
        )
    else:
        how = (
            f"omit {source_flag} so the release binds {tip}: its own passing "
            f"or running {target.workflow} run is reused, and only a tip with "
            "no run gets one dispatch. Or name a commit whose own run passed."
        )
    finding = (
        "has no run of its own" if state == "no_runs" else f"has run state {state}"
    )
    return ReleaseSourceRefused(
        UNTESTED,
        compose_refusal(
            f"release commit {lineage} {finding} in {target.workflow} on "
            f"{target.repo} (runs on any branch at exactly this commit count; "
            "pull_request and merge_group runs do not), so flow "
            f"'{target.flow}' would block at its CI gate. Nothing was bound.",
            recovery=how,
        ),
    )


def require_tested_lineage(
    project: str,
    flow: str,
    environment: Optional[str],
    release_lineage: Optional[str],
    *,
    retry: bool = False,
    source_flag: str = CREATE_SOURCE_FLAG,
) -> None:
    lineage = (release_lineage or "").strip()
    if not _FULL_SHA.fullmatch(lineage):
        # Empty is settled by the caller; an annotated release tag is peeled
        # at execution, where the gate reads the peeled commit's own run.
        return
    target = ci_gate_target(project, flow, environment)
    if target is None or not target.workflow:
        return
    state = _proof_state(target, lineage)
    if state not in _TESTED_STATES:
        raise _untested(target, lineage, state, retry, source_flag)


def bind_tested_release_source(
    project: str,
    flow: str,
    environment: Optional[str],
    release_lineage: Optional[str],
    *,
    retry: bool = False,
    source_flag: str = CREATE_SOURCE_FLAG,
) -> Optional[str]:
    """The commit a new release binds, or ``None`` when its flow binds none.

    *source_flag* is how the calling command names an explicit source, so
    every recovery names a flag that command accepts.
    """
    if (release_lineage or "").strip():
        require_tested_lineage(project, flow, environment, release_lineage,
                               retry=retry, source_flag=source_flag)
        return release_lineage
    target = ci_gate_target(project, flow, environment)
    if target is None:
        return release_lineage
    selected = gate_branch_tip(target)
    state = _proof_state(target, selected) if target.workflow else "passed"
    if state == "no_runs":
        selected = dispatch_branch_ci(target)
    elif state not in _TESTED_STATES:
        raise ReleaseSourceRefused(
            "release_source_ci_failed",
            compose_refusal(
                f"gate branch tip {selected} on {target.repo}@{target.branch} "
                f"has {target.workflow} run state {state}: its newest run on "
                "exactly that commit did not pass, and an older green attempt "
                "never stands in for it. Nothing was bound.",
                recovery=(
                    f"fix {target.branch} or rerun that commit's CI, then run "
                    "the same command again."
                ),
            ),
        )
    require_descends_from_previous_release(target, selected, source_flag)
    return selected


__all__ = [
    "CREATE_SOURCE_FLAG",
    "CiGateTarget",
    "ReleaseSourceRefused",
    "UNTESTED",
    "UNVERIFIABLE",
    "bind_tested_release_source",
    "ci_gate_target",
    "START_SOURCE_FLAG",
    "dispatch_branch_ci",
    "require_tested_lineage",
]
