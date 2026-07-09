"""Deployment-pipeline executor entrypoints.

Simple stage executors the deployment pipeline in
:mod:`yoke_core.domain.deploy_pipeline` dispatches via in-process calls.
Heavier executors own their own modules (``deploy_core_container``,
``deploy_environment_activate``).

Each executor returns an integer exit code:

- ``exec_auto``           -> always ``0`` (no-op for stages that need no action)
- ``exec_health_check``   -> ``0`` on HTTP 2xx, ``1`` on failure. With
  ``request_id`` it sends ``x-request-id`` and requires the response to echo
  it (the Yoke core request-id propagation contract). With
  ``require_schema_ready`` the JSON body must report ``schema_ready: true``
  (the deployed core's DB carries its expected schema surface).
- ``exec_ephemeral_verify`` -> ``0`` with ``EPHEMERAL_URL=<url>`` printed on
  success, ``1`` otherwise.  Preserves the stdout contract that
  :func:`yoke_core.domain.deploy_pipeline._dispatch_ephemeral_verify`
  parses for ``EPHEMERAL_URL=``.

The module is also usable as a CLI for ad-hoc invocation:

    python3 -m yoke_core.tools.executors auto
    python3 -m yoke_core.tools.executors health-check <url> [request-id]
    python3 -m yoke_core.tools.executors ephemeral-verify <repo> <branch> <workflow> <domain> [sha]

The CLI exits with the same code the Python function returns.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import List, Optional

# Clock aliases so the warmup loop's timing is monkeypatchable in tests.
_monotonic = time.monotonic
_sleep = time.sleep

from yoke_core.domain.ephemeral_substrate import slugify_branch
from yoke_core.domain.github_actions_rest import (
    latest_workflow_run,
    resolve_token,
)


# ---------------------------------------------------------------------------
# exec-auto
# ---------------------------------------------------------------------------


def exec_auto() -> int:
    """No-op executor for stages that require no action."""
    print("exec-auto: stage complete (no-op)")
    return 0


# ---------------------------------------------------------------------------
# exec-health-check
# ---------------------------------------------------------------------------


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

    When *require_schema_ready* is true the response body MUST be JSON
    whose ``schema_ready`` is ``true`` — proof the DB behind the deployed
    core carries its expected schema surface, not just an HTTP-live
    process over an uninitialized DB whose data routes fail. Only the
    Yoke core health endpoint serves ``schema_ready``, so callers set
    this only on env-resolved checks.

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


# ---------------------------------------------------------------------------
# exec-ephemeral-verify
# ---------------------------------------------------------------------------


def _gh_runs_for_workflow(
    github_repo: str, workflow: str, *, branch: str = "", commit_sha: str = ""
) -> Optional[dict]:
    """Return the most recent workflow run metadata, or ``None``.

    bearer-token via :func:`github_actions_rest.latest_workflow_run` when
    queried by branch. ``commit_sha`` lookups go through a thin REST
    call because the helper only exposes the branch path; both shapes
    return the same upstream ``workflow_runs[0]`` envelope so callers
    read ``id`` / ``status`` / ``conclusion`` / ``created_at`` unchanged.
    """
    if not branch and not commit_sha:
        return None
    token = resolve_token("yoke")
    if branch:
        return latest_workflow_run(github_repo, workflow, branch=branch, token=token)

    from yoke_core.domain.github_actions_rest import rest_get
    from yoke_core.domain.gh_rest_transport import RestTransportError

    try:
        data = rest_get(
            f"/repos/{github_repo}/actions/workflows/{workflow}/runs",
            query={"head_sha": commit_sha, "per_page": "1"},
            token=token,
        )
    except RestTransportError:
        return None
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
) -> int:
    """Verify the ephemeral deploy workflow succeeded and print preview URL.

    Preserves the shell contract: on success prints human-readable progress
    and a trailing ``EPHEMERAL_URL=<url>`` line that
    :mod:`yoke_core.domain.deploy_pipeline` parses.
    """
    if not github_repo or not workflow:
        print(
            "Usage: exec_ephemeral_verify(github_repo, branch, workflow, domain, commit_sha='')",
            file=sys.stderr,
        )
        return 1
    if not branch and not commit_sha:
        print(
            "Error: at least one of <branch> or <commit_sha> must be provided",
            file=sys.stderr,
        )
        return 1
    if not domain:
        print(
            "Error: domain not provided — cannot compute preview URL",
            file=sys.stderr,
        )
        return 1

    run_data: Optional[dict] = None
    if branch:
        print(f"  Looking for ephemeral deploy run: {workflow} on branch {branch}...")
        run_data = _gh_runs_for_workflow(github_repo, workflow, branch=branch)
        if run_data is None:
            print("  No run found by branch, trying SHA fallback...", file=sys.stderr)
    if run_data is None and commit_sha:
        print(f"  Looking for ephemeral deploy run: {workflow} @ {commit_sha}...")
        run_data = _gh_runs_for_workflow(github_repo, workflow, commit_sha=commit_sha)

    if run_data is None:
        sha_label = commit_sha or "none"
        branch_label = branch or "none"
        print(
            f"  No ephemeral deploy run found (SHA: {sha_label}, branch: {branch_label})",
            file=sys.stderr,
        )
        print("  The ephemeral deploy workflow may not have triggered.", file=sys.stderr)
        return 1

    run_id = run_data.get("id", "")
    run_status = run_data.get("status", "")
    run_conclusion = run_data.get("conclusion", "") or ""
    run_created = run_data.get("created_at", "")
    print(
        f"  Found run {run_id} (status: {run_status}, conclusion: {run_conclusion}, "
        f"created: {run_created})"
    )

    if run_status != "completed":
        print(
            f"  Ephemeral deploy run {run_id} is still {run_status} — not yet complete",
            file=sys.stderr,
        )
        return 1
    if run_conclusion != "success":
        print(
            f"  Ephemeral deploy run {run_id} concluded with: {run_conclusion}",
            file=sys.stderr,
        )
        return 1

    slug = slugify_branch(branch)
    preview_url = f"https://{slug}.{domain}"
    print("  Ephemeral deploy verified successfully")
    print(f"  Preview URL: {preview_url}")
    print(f"EPHEMERAL_URL={preview_url}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "Usage: python3 -m yoke_core.tools.executors "
            "{auto|health-check|ephemeral-verify} [args...]",
            file=sys.stderr,
        )
        return 1
    cmd = args[0]
    rest = args[1:]
    if cmd == "auto":
        return exec_auto()
    if cmd == "health-check":
        if len(rest) not in (1, 2):
            print(
                "Usage: python3 -m yoke_core.tools.executors health-check "
                "<url> [request-id]",
                file=sys.stderr,
            )
            return 1
        return exec_health_check(
            rest[0], request_id=rest[1] if len(rest) == 2 else ""
        )
    if cmd == "ephemeral-verify":
        if len(rest) < 4 or len(rest) > 5:
            print(
                "Usage: python3 -m yoke_core.tools.executors ephemeral-verify "
                "<github_repo> <branch> <workflow> <domain> [commit_sha]",
                file=sys.stderr,
            )
            return 1
        commit_sha = rest[4] if len(rest) == 5 else ""
        return exec_ephemeral_verify(rest[0], rest[1], rest[2], rest[3], commit_sha)
    print(f"Error: unknown executor '{cmd}'", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
