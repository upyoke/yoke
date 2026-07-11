"""Deployment pipeline reporting helpers — subprocess wrappers, events, GH poll.

Extracted from :mod:`yoke_core.domain.deploy_pipeline` as the
reporting/status output slice. Gate logic (gate-branch resolution, merged
gate, CI gate) lives in :mod:`yoke_core.domain.deploy_pipeline_gates`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


GITHUB_ACTIONS_RELAY_ENV = "YOKE_GITHUB_ACTIONS_RELAY_ENV"
GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV = "YOKE_GITHUB_ACTIONS_LOCAL_AUTHORITY"


# ---------------------------------------------------------------------------
# Low-level subprocess helpers
# ---------------------------------------------------------------------------

def _run_cmd(cmd: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _github_actions(
    *args: str,
    project: str,
    sd: Optional[str] = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    # HTTPS deploy clients relay through the typed Yoke function boundary so
    # GitHub App private-key authority remains inside the control plane. Local
    # source-dev/operator bootstraps use the same typed adapter with a narrow
    # local-only dispatcher, preserving intent/idempotency semantics while the
    # hosted relay is being introduced or repaired.
    del sd
    explicit_relay_env = os.environ.get(GITHUB_ACTIONS_RELAY_ENV, "").strip()
    local_authority = os.environ.get(
        GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, ""
    ).strip()
    if explicit_relay_env and local_authority:
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=4,
            stdout="",
            stderr=(
                "Error: GitHub Actions authority is ambiguous; set either "
                f"{GITHUB_ACTIONS_RELAY_ENV} or "
                f"{GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV}=1, not both\n"
            ),
        )
    if local_authority not in ("", "1"):
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=4,
            stdout="",
            stderr=(
                f"Error: {GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV} must be 1 when "
                "selecting the attended local App authority\n"
            ),
        )
    https = None
    if explicit_relay_env:
        try:
            from yoke_cli.transport.https import (
                TransportError,
                resolve_https_connection,
            )

            https = resolve_https_connection(explicit_env=explicit_relay_env)
        except TransportError as exc:
            return subprocess.CompletedProcess(
                args=list(args),
                returncode=4,
                stdout="",
                stderr=(
                    "Error: https GitHub Actions relay is misconfigured: "
                    f"{exc}\n"
                ),
            )
    if explicit_relay_env and https is None:
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=4,
            stdout="",
            stderr=(
                f"Error: {GITHUB_ACTIONS_RELAY_ENV} selects "
                f"{explicit_relay_env!r}, but that connection is not HTTPS; "
                "refusing local GitHub credential fallback\n"
            ),
        )
    if https is not None:
        return _run_cmd(
            [
                sys.executable,
                "-m",
                "yoke_cli.main",
                "--env",
                explicit_relay_env,
                "github-actions",
                *args,
                "--project",
                project,
            ],
            timeout=timeout,
        )
    if not local_authority:
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=4,
            stdout="",
            stderr=(
                "Error: no GitHub Actions authority selected; set "
                f"{GITHUB_ACTIONS_RELAY_ENV}=<https-env> for normal deploys "
                f"or {GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV}=1 for an attended "
                "control-plane bootstrap\n"
            ),
        )
    return _run_cmd(
        [
            sys.executable,
            "-m",
            "yoke_cli.main",
            "github-actions",
            *args,
            "--project",
            project,
        ],
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Script-dir / DB dispatch helpers
# ---------------------------------------------------------------------------

def _resolve_script_dir() -> str:
    from yoke_core.api.repo_root import find_repo_root

    return str(find_repo_root(Path(__file__)) / ".agents" / "skills" / "yoke" / "scripts")


def _yoke_db(*args: str, sd: Optional[str] = None) -> str:
    # Route through the Python db_router entrypoint.
    r = _run_cmd([sys.executable, "-m", "yoke_core.cli.db_router"] + list(args))
    return r.stdout.strip()


def _flow_db(*args: str, sd: Optional[str] = None) -> str:
    # route through Python owner (replaces flow-db.sh shim).
    r = _run_cmd([sys.executable, "-m", "yoke_core.domain.flow"] + list(args))
    return r.stdout.strip()


def _project_db(*args: str, sd: Optional[str] = None) -> str:
    # route through Python owner (replaces project-db.sh shim).
    r = _run_cmd([sys.executable, "-m", "yoke_core.domain.projects"] + list(args))
    return r.stdout.strip()


def _emit_event(*args: str, sd: Optional[str] = None) -> None:
    """Emit an event via the native Python emitter.

    Accepts the legacy ``--flag value`` argv style; the shared helper in
    :mod:`yoke_core.domain.events` parses and dispatches to
    :func:`emit_event` in-process. Non-fatal on failure.
    """
    del sd  # unused — kept for backwards-compatible signature
    try:
        from yoke_core.domain.events import emit_event_argv
        emit_event_argv(list(args))
    except Exception:
        pass


def _parse_stages(stages_json: str) -> List[Dict[str, Any]]:
    """Parse flow stages JSON into dicts with name, executor, kind, config.

    Executor-shaped stages carry explicit ``name`` + ``executor`` keys.
    Kind-shaped stages (e.g. ``{"kind": "migration_apply", ...}``) carry
    neither in the flow row; the pipeline derives a stable stage name
    from the kind (underscores → hyphens, e.g. ``migration-apply``) so
    ``deployment_runs.current_stage``, ``--from-stage`` resume, and stage
    telemetry can address the stage without mutating live flow rows. An
    operator-authored ``name`` on the stage object wins over the derived
    one. The ``executor`` label mirrors the kind for display/telemetry;
    dispatch branches on ``kind`` before the executor vocabulary.
    """
    stages = json.loads(stages_json)
    parsed: List[Dict[str, Any]] = []
    for s in stages:
        kind = str(s.get("kind", "") or "")
        parsed.append({
            "name": str(s.get("name", "") or kind.replace("_", "-")),
            "executor": str(s.get("executor", "") or kind),
            "kind": kind,
            "config": s,
        })
    return parsed


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------

def _emit_run_event(
    name: str,
    outcome: str,
    context: Dict[str, Any],
    *,
    member_items: List[str],
    project: str = "yoke",
    sd: Optional[str] = None,
) -> None:
    """Emit deployment run event, one per member item."""
    ctx_json = json.dumps(context)
    targets = member_items if member_items else [""]
    for item_id in targets:
        args = [
            "--name", name,
            "--kind", "lifecycle",
            "--type", "deployment_run",
            "--source-type", "system",
            "--severity", "STATUS",
            "--project", project,
            "--outcome", outcome,
            "--context", ctx_json,
        ]
        if item_id:
            args += ["--item-id", item_id]
        _emit_event(*args, sd=sd)


# ---------------------------------------------------------------------------
# Dual-write deploy_stage
# ---------------------------------------------------------------------------

def _set_deploy_stage(
    stage: str,
    run_id: str,
    member_items: List[str],
    *,
    sd: Optional[str] = None,
) -> None:
    """Update run's current_stage + each member item's deploy_stage (dual-write)."""
    _yoke_db("runs", "update", run_id, "current_stage", stage, sd=sd)
    for item_id in member_items:
        _yoke_db("items", "update", item_id, "deploy_stage", stage, sd=sd)


# ---------------------------------------------------------------------------
# GitHub Actions poll loop
# ---------------------------------------------------------------------------

# A queued GitHub Actions workflow has not yet acquired a runner; a transient
# transport or subprocess failure can return an exit code not in {0,1,2,3}.
# A single such response is not proof the workflow failed — bounded-retry
# before declaring stage failure so the configured timeout budget is used for
# what it was budgeted for.
POLL_TRANSIENT_RETRY_LIMIT = 5


def _poll_github_actions(
    github_repo: str,
    run_id: str,
    timeout_sec: int,
    stage_name: str = "",
    *,
    project: str,
    sd: Optional[str] = None,
) -> Tuple[int, str]:
    """Poll a GitHub Actions run to completion.

    Returns (exit_code, output).  0=success, 1=failed.
    """
    start = time.time()

    # Adaptive polling intervals
    initial = 5
    if any(stage_name.startswith(p) for p in ("smoke", "verify", "health", "check")):
        max_interval = 10
    else:
        max_interval = 30
    interval = initial
    transient_retries = 0

    while True:
        elapsed = int(time.time() - start)
        if elapsed >= timeout_sec:
            return 1, f"Error: GitHub Actions poll timed out after {timeout_sec}s"

        r = _github_actions(
            "poll", github_repo, run_id, project=project, sd=sd,
        )
        output = r.stdout.strip()
        stderr = (r.stderr or "").strip()

        if r.returncode == 0:
            return 0, output
        if r.returncode == 1:
            # Real workflow failure. Include stderr for diagnostics so the
            # caller can surface it on DeploymentRunStageFailed without
            # manual log archaeology.
            return 1, _compose_poll_diagnostic(output, stderr)
        if r.returncode in (2, 3):
            print(f"  Workflow status: {output} (elapsed: {elapsed}s, next poll: {interval}s)")
            time.sleep(interval)
            interval = min(interval * 2, max_interval)
            transient_retries = 0
        else:
            transient_retries += 1
            if transient_retries >= POLL_TRANSIENT_RETRY_LIMIT:
                diag = _compose_poll_diagnostic(output, stderr)
                return 1, (
                    f"Error: GitHub Actions poll returned unexpected exit code {r.returncode} "
                    f"after {transient_retries} retries: {diag}"
                )
            print(
                f"  Transient GitHub Actions poll error (exit={r.returncode}, "
                f"retry {transient_retries}/{POLL_TRANSIENT_RETRY_LIMIT}): "
                f"{stderr or output}"
            )
            time.sleep(interval)
            interval = min(interval * 2, max_interval)


def _compose_poll_diagnostic(stdout: str, stderr: str) -> str:
    """Combine GitHub Actions poll stdout and stderr for failure event payloads."""
    parts = [s for s in (stdout, stderr) if s]
    return "\n".join(parts) if parts else ""


# Branch-gate + CI-gate logic lives in deploy_pipeline_gates
# (resolve_flow_gate_branch, _resolve_and_verify_branch,
# _verify_branch_merged, _check_ci_gate).
