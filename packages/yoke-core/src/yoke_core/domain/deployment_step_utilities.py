"""Deployment health probes and ephemeral workflow verification."""
from __future__ import annotations
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Optional
from yoke_contracts.health_payload_contract import migration_readiness_problem
from yoke_core.domain.github_actions_rest import latest_workflow_run, resolve_token
from yoke_core.domain.step_runners_ephemeral_verify import verify_ephemeral_workflow

_monotonic = time.monotonic



_sleep = time.sleep



def exec_auto() -> int:
    """No-op step runner for stages that require no action."""
    print("exec-auto: stage complete (no-op)")
    return 0



def exec_health_check(
    url: str,
    *,
    timeout: float = 10.0,
    request_id: str = "",
    expected_build: str = "",
    require_schema_ready: bool = False,
    warmup_timeout: float = 0.0,
    retry_interval: float = 6.0,
) -> int:
    """HTTP GET against *url*; return 0 for 2xx, 1 otherwise.

    When *request_id* is provided the request carries it as ``x-request-id``
    and the response MUST echo the same value back — the Yoke core
    request-id propagation contract (request-id propagation). Plain checks against
    third-party endpoints omit ``request_id`` and skip the echo assertion.

    When *expected_build* is provided the response body MUST be JSON whose
    ``build`` equals it — proof the NEW code is answering, not a stale
    container that survived a silently failed swap. Only the Yoke core
    health endpoint serves ``build``, so callers set this only on
    env-resolved checks.

    When *require_schema_ready* is true the response body MUST be JSON whose
    ``schema_ready`` is ``true`` and whose migration fields do not explicitly
    refuse service — proof the DB behind the deployed core carries its expected
    surface and can be served by that artifact, not just an HTTP-live process.
    Only the Yoke core health endpoint serves these fields, so callers set this
    only on env-resolved checks.

    When *warmup_timeout* > 0 the check retries every *retry_interval* seconds
    until it passes or the budget elapses; the build and schema assertions
    still gate each attempt, so a failed swap never passes. Default 0.0 keeps
    it single-shot.
    """
    if not url:
        print("Usage: exec_health_check(url)", file=sys.stderr)
        return 1
    deadline = _monotonic() + warmup_timeout
    attempt = 0
    while True:
        attempt += 1
        rc = _attempt_health_check(
            url, timeout=timeout, request_id=request_id,
            expected_build=expected_build,
            require_schema_ready=require_schema_ready,
        )
        if rc == 0:
            return 0
        if warmup_timeout <= 0 or _monotonic() >= deadline:
            return rc
        print(
            f"exec-health-check: {url} not ready yet (attempt {attempt}); "
            f"retrying in {retry_interval:g}s during the {warmup_timeout:g}s "
            "warmup window...",
            file=sys.stderr,
        )
        _sleep(retry_interval)



def _attempt_health_check(
    url: str,
    *,
    timeout: float,
    request_id: str,
    expected_build: str,
    require_schema_ready: bool = False,
) -> int:
    """One health probe: 0 on 2xx with all contract checks passing, 1 otherwise."""
    headers = {"x-request-id": request_id} if request_id else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if not 200 <= int(status) < 300:
                print(
                    f"exec-health-check: {url} failed health check (status {status})",
                    file=sys.stderr,
                )
                return 1
            if request_id:
                echoed = resp.headers.get("x-request-id", "")
                if echoed != request_id:
                    print(
                        f"exec-health-check: {url} returned {status} but did "
                        f"not echo x-request-id '{request_id}' "
                        f"(got '{echoed}'); request-id propagation contract "
                        "violated",
                        file=sys.stderr,
                    )
                    return 1
            body: dict = {}
            if expected_build or require_schema_ready:
                try:
                    parsed = json.loads(resp.read().decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    body = parsed
            if expected_build:
                served_build = str(body.get("build", ""))
                if served_build != expected_build:
                    print(
                        f"exec-health-check: {url} returned {status} but "
                        f"serves build '{served_build}', expected "
                        f"'{expected_build}' — the deployed container is "
                        "not running the deployed code (swap failed or a "
                        "stale image answered)",
                        file=sys.stderr,
                    )
                    return 1
            if require_schema_ready and body.get("schema_ready") is not True:
                missing = body.get("schema_missing_tables")
                detail = (
                    f" (missing tables: {', '.join(str(t) for t in missing)})"
                    if isinstance(missing, list) and missing
                    else ""
                )
                print(
                    f"exec-health-check: {url} returned {status} but does "
                    f"not report schema_ready=true{detail} — the deployed "
                    "core's DB lacks part of the expected schema surface, "
                    "so routes touching it fail despite HTTP liveness",
                    file=sys.stderr,
                )
                return 1
            if require_schema_ready:
                migration_problem = migration_readiness_problem(
                    body,
                    # Deploy probes can span a rolling upgrade from a build
                    # predating these fields. Missing remains compatible;
                    # explicit false is authoritative and fails closed.
                    require_current=False,
                )
                if migration_problem:
                    print(
                        f"exec-health-check: {url} returned {status} but "
                        f"{migration_problem}",
                        file=sys.stderr,
                    )
                    return 1
            suffix = ""
            if request_id:
                suffix += f" (request-id {request_id} echoed)"
            if expected_build:
                suffix += f" (build {expected_build} confirmed)"
            if require_schema_ready:
                suffix += " (schema ready)"
            print(f"exec-health-check: {url} returned {status}{suffix}")
            return 0
    except urllib.error.HTTPError as exc:
        print(
            f"exec-health-check: {url} failed health check ({exc.code})",
            file=sys.stderr,
        )
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(
            f"exec-health-check: {url} failed health check ({exc})",
            file=sys.stderr,
        )
        return 1



def _gh_runs_for_workflow(
    github_repo: str,
    workflow: str,
    *,
    project: str,
    branch: str = "",
    commit_sha: str = "",
) -> Optional[dict]:
    """Return the most recent workflow run metadata, or ``None``.

    bearer-token via :func:`github_actions_rest.latest_workflow_run` when
    queried by branch. A ``commit_sha`` lookup stays a thin REST call so a
    preview whose workflow is absent reports "no run yet" rather than
    raising; both shapes return the same upstream ``workflow_runs[0]``
    envelope, read as ``id`` / ``status`` / ``conclusion`` / ``created_at``.
    """
    if not branch and not commit_sha:
        return None
    from yoke_contracts.github_app_installation_permissions import (
        GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )

    token = resolve_token(
        project,
        github_repo,
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    if branch:
        return latest_workflow_run(github_repo, workflow, branch=branch, token=token)

    from yoke_core.domain.github_actions_rest import rest_get
    data = rest_get(
        f"/repos/{github_repo}/actions/workflows/{workflow}/runs",
        query={"head_sha": commit_sha, "per_page": "1"},
        token=token,
    )
    if not isinstance(data, dict):
        return None
    runs = data.get("workflow_runs")
    if not isinstance(runs, list) or not runs:
        return None
    first = runs[0]
    return first if isinstance(first, dict) else None



def exec_ephemeral_verify(
    github_repo: str,
    branch: str,
    workflow: str,
    domain: str,
    commit_sha: str = "",
    *,
    project: str,
) -> int:
    """Verify the deploy workflow and preserve the ``EPHEMERAL_URL`` contract."""
    return verify_ephemeral_workflow(
        github_repo,
        branch,
        workflow,
        domain,
        commit_sha,
        project=project,
        run_lookup=_gh_runs_for_workflow,
    )

