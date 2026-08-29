"""Control-plane adapters for deployment failure-chain analysis."""

from __future__ import annotations

import re
from typing import Any, Mapping

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.deployment_failure_trace import (
    FailedJob,
    RunRef,
    RunSnapshot,
    github_run_ref,
    walk_failure_chain,
)


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return row[index]


def _partial(run_id: str, stage: str, reason: str, recovery: str) -> dict[str, Any]:
    return {
        "deployment_run_id": run_id,
        "stage": stage,
        "complete": False,
        "chain": [],
        "terminal_job": "",
        "terminal_error": "",
        "stop_reason": reason,
        "recovery": recovery,
    }


def trace_deployment_failure(run_id: str, *, actor_id: int | None) -> dict[str, Any]:
    """Resolve a deployment's dispatch intent and walk its failure chain."""
    from yoke_core.domain.actor_permissions import PERM_GITHUB_ACTIONS_RUN_READ
    from yoke_core.domain.actor_project_visibility import (
        actor_project_ids_with_permission,
    )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deploy_pipeline_github_workflow_inputs import (
        workflow_dispatch_request_id,
    )
    from yoke_core.domain.project_github_binding import normalize_github_repo

    with connect() as conn:
        run = conn.execute(
            "SELECT dr.id AS run_id, p.id AS project_id, "
            "p.slug AS project_slug, dr.status, "
            "COALESCE(dr.current_stage, '') AS current_stage "
            "FROM deployment_runs dr JOIN projects p ON p.id=dr.project_id "
            "WHERE dr.id=%s",
            (run_id,),
        ).fetchone()
        if run is None:
            raise LookupError(f"deployment run {run_id!r} was not found")
        project_id = int(_row_value(run, "project_id", 1))
        project_slug = str(_row_value(run, "project_slug", 2))
        status = str(_row_value(run, "status", 3))
        current_stage = str(_row_value(run, "current_stage", 4))
        stage = current_stage.removesuffix("-failed")
        visible = actor_project_ids_with_permission(
            conn,
            actor_id,
            PERM_GITHUB_ACTIONS_RUN_READ,
        )
        if visible is not None and project_id not in visible:
            raise PermissionError(
                f"actor lacks {PERM_GITHUB_ACTIONS_RUN_READ!r} on {project_slug}"
            )
        request_id = workflow_dispatch_request_id(project_slug, run_id, stage)
        intent = conn.execute(
            "SELECT repo, workflow_run_id FROM github_workflow_dispatch_intents "
            "WHERE request_id=%s AND state='completed' "
            "ORDER BY attempt DESC LIMIT 1",
            (request_id,),
        ).fetchone()
        projects = conn.execute(
            "SELECT id AS project_id, slug AS project_slug, github_repo "
            "FROM projects WHERE github_repo IS NOT NULL ORDER BY id",
        ).fetchall()
    if status != "failed":
        raise ValueError(f"deployment run {run_id} is {status!r}, not failed")
    if not stage:
        raise ValueError(f"deployment run {run_id} has no failed stage")
    if intent is None:
        return _partial(
            run_id,
            stage,
            f"no completed workflow dispatch intent exists for {request_id}",
            "inspect the deployment stage output and restore its dispatch intent",
        )
    origin = github_run_ref(
        str(_row_value(intent, "repo", 0)),
        str(_row_value(intent, "workflow_run_id", 1)),
    )
    project_rows = [
        (
            int(_row_value(row, "project_id", 0)),
            str(_row_value(row, "project_slug", 1)),
            normalize_github_repo(_row_value(row, "github_repo", 2)),
        )
        for row in projects
    ]
    tokens: dict[str, str] = {}

    def token_for(repo: str) -> str:
        wanted = normalize_github_repo(repo)
        matches = [row for row in project_rows if row[2] == wanted]
        if len(matches) != 1:
            raise LookupError(
                f"expected one registered project for {wanted}, found {len(matches)}"
            )
        downstream_id, downstream_slug, _repo = matches[0]
        if visible is not None and downstream_id not in visible:
            raise PermissionError(
                f"actor lacks {PERM_GITHUB_ACTIONS_RUN_READ!r} on {downstream_slug}"
            )
        if wanted not in tokens:
            from yoke_core.domain.project_github_auth import (
                resolve_project_github_auth,
            )

            auth = resolve_project_github_auth(
                downstream_slug,
                required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
            )
            if normalize_github_repo(auth.repo) != wanted:
                raise PermissionError(
                    f"project {downstream_slug!r} is not bound to {wanted}"
                )
            tokens[wanted] = auth.token
        return tokens[wanted]

    def inspect(ref: RunRef) -> RunSnapshot:
        from yoke_core.domain.github_actions_logs import fetch_job_log
        from yoke_core.domain.github_actions_rest import rest_get

        token = token_for(ref.repo)
        listing = rest_get(
            f"/repos/{ref.repo}/actions/runs/{ref.run_id}/jobs",
            query={"filter": "all", "per_page": "100"},
            token=token,
        )
        if not isinstance(listing, dict) or not isinstance(listing.get("jobs"), list):
            raise ValueError("workflow jobs response omitted jobs")
        jobs = [job for job in listing["jobs"] if isinstance(job, dict)]
        total = listing.get("total_count")
        if isinstance(total, int) and total > len(jobs):
            raise ValueError(f"run has {total} jobs; only {len(jobs)} were returned")
        failures: list[FailedJob] = []
        for job in jobs:
            if str(job.get("conclusion") or "") != "failure":
                continue
            job_id = str(job.get("id") or "")
            name = str(job.get("name") or f"job-{job_id}")
            try:
                failures.append(
                    FailedJob(
                        job_id,
                        name,
                        fetch_job_log(ref.repo, job_id, token=token),
                    )
                )
            except Exception as exc:
                failures.append(FailedJob(job_id, name, "", str(exc)))
        return RunSnapshot(ref, tuple(failures))

    def resolve_job(repo: str, job_id: str) -> RunRef:
        from yoke_core.domain.github_actions_rest import rest_get

        data = rest_get(
            f"/repos/{repo}/actions/jobs/{job_id}",
            token=token_for(repo),
        )
        if not isinstance(data, dict):
            raise LookupError("job response was not found")
        match = re.search(
            r"/actions/runs/(?P<run>\d+)$",
            str(data.get("run_url") or ""),
        )
        if match is None:
            raise ValueError("job response omitted its run URL")
        return github_run_ref(repo, match.group("run"))

    walked = walk_failure_chain(origin, inspect_run=inspect, resolve_job=resolve_job)
    return {"deployment_run_id": run_id, "stage": stage, **walked}


__all__ = ["trace_deployment_failure"]
