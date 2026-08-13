"""Deployment pipeline subprocess, event, status, and GitHub-poll helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from yoke_core.domain import deploy_pipeline_poll_authority as poll_authority
from yoke_core.domain.github_poll_schedule import (
    STEADY_SCHEDULE,
    PollSchedule,
    next_read_delay,
)


GITHUB_ACTIONS_RELAY_ENV = "YOKE_GITHUB_ACTIONS_RELAY_ENV"
GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV = "YOKE_GITHUB_ACTIONS_LOCAL_AUTHORITY"


def _run_cmd(cmd: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _github_actions(
    *args: str,
    project: str,
    sd: Optional[str] = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    # HTTPS deploy clients relay through a peer control plane so GitHub App
    # private-key authority stays off the runner and off the plane under
    # deploy. Local source-dev/operator bootstraps use the same typed adapter
    # with a narrow local-only dispatcher.
    del sd
    local_authority = os.environ.get(
        GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, ""
    ).strip()
    explicit_relay_env = os.environ.get(GITHUB_ACTIONS_RELAY_ENV, "").strip()
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
    relay_env, relay_source = poll_authority.resolve_status_relay_env()
    if local_authority:
        relay_env, relay_source = None, ""

    https = None
    if relay_env:
        try:
            from yoke_cli.transport.https import (
                TransportError,
                resolve_https_connection,
            )

            https = resolve_https_connection(explicit_env=relay_env)
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
    if relay_env and https is None:
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=4,
            stdout="",
            stderr=(
                f"Error: {relay_source} selects "
                f"{relay_env!r}, but that connection is not HTTPS; "
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
                relay_env,
                "github-actions",
                *args,
                "--project",
                project,
            ],
            timeout=timeout,
        )
    if not local_authority:
        peers = ", ".join(
            f"{base}→{peer}"
            for base, peer in sorted(poll_authority.HOSTED_STATUS_PEERS.items())
        )
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=4,
            stdout="",
            stderr=(
                "Error: no GitHub Actions authority selected; set "
                f"{GITHUB_ACTIONS_RELAY_ENV}=<peer-https-env> for a plane "
                "that fails independently of the deploy target "
                f"(known peers: {peers}), or "
                f"{GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV}=1 for an attended "
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


def _parse_stages(stages_json: str) -> List[Dict[str, Any]]:
    """Parse flow stages JSON into dicts with name, step_runner, and config.

    Every stage carries an explicit ``name`` and ``step_runner``, which
    ``deployment_runs.current_stage``, ``--from-stage`` resume, and stage
    telemetry address it by.
    """
    stages = json.loads(stages_json)
    return [
        {
            "name": str(s.get("name", "") or ""),
            "step_runner": str(s.get("step_runner", "") or ""),
            "config": s,
        }
        for s in stages
    ]


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
# Exit code 4 is the Yoke CLI's hosted-transport failure. A release may
# temporarily replace the same service used to query GitHub, so that condition
# consumes the stage's existing timeout budget instead of an unrelated short
# retry cap. Other unexpected subprocess failures remain bounded.
POLL_UNCLASSIFIED_RETRY_LIMIT = 5


def _poll_github_actions(
    github_repo: str,
    run_id: str,
    timeout_sec: int,
    *,
    project: str,
    sd: Optional[str] = None,
    schedule: PollSchedule = STEADY_SCHEDULE,
) -> Tuple[int, str]:
    """Poll a GitHub Actions run to completion.

    Returns (exit_code, output).  0=success, 1=failed.

    Reads follow *schedule*, which defaults to the plain minimum-interval
    cadence a deploy stage wants: a stage can conclude at any moment, so
    there is no stretch of it worth skipping. A caller waiting on a run
    with a known duration floor — the CI suite behind the verification
    gate — passes that run's schedule instead.
    """
    start = time.time()
    transport_retries = 0
    unclassified_retries = 0
    # Named on every run, not only when it breaks: an operator reading a
    # stalled poll should not have to infer which authority it is using.
    print(f"  GitHub Actions status via {poll_authority.authority_label()}")

    while True:
        elapsed = int(time.time() - start)
        if elapsed >= timeout_sec:
            return 1, f"Error: GitHub Actions poll timed out after {timeout_sec}s"

        r = _github_actions(
            "poll", github_repo, run_id, project=project, sd=sd,
        )
        output = r.stdout.strip()
        stderr = (r.stderr or "").strip()
        # One schedule for every reason to read again: a run that has not
        # concluded and a relay that could not be reached are both answered
        # by the same next scheduled read.
        interval = next_read_delay(time.time() - start, schedule)

        if r.returncode == 0:
            return 0, output
        if r.returncode == 1:
            # Real workflow failure. Include stderr for diagnostics so the
            # caller can surface it on DeploymentRunStageFailed without
            # manual log archaeology.
            return 1, _compose_poll_diagnostic(output, stderr)
        if r.returncode in (2, 3):
            print(
                f"  Workflow status: {output} (elapsed: {elapsed}s, "
                f"next poll: {int(interval)}s)"
            )
            time.sleep(interval)
            transport_retries = 0
            unclassified_retries = 0
        elif r.returncode == 4:
            transport_retries += 1
            if transport_retries < poll_authority.ESCALATE_AFTER:
                print(
                    "  GitHub Actions status relay is temporarily "
                    f"unavailable; retrying within the {timeout_sec}s stage "
                    f"budget (consecutive failure {transport_retries}): "
                    f"{stderr or output}"
                )
            elif poll_authority.should_report(transport_retries):
                print(
                    poll_authority.stall_message(run_id, transport_retries)
                )
            time.sleep(interval)
        else:
            unclassified_retries += 1
            if unclassified_retries >= POLL_UNCLASSIFIED_RETRY_LIMIT:
                diag = _compose_poll_diagnostic(output, stderr)
                return 1, (
                    f"Error: GitHub Actions poll returned unexpected exit code {r.returncode} "
                    f"after {unclassified_retries} retries: {diag}"
                )
            print(
                f"  Transient GitHub Actions poll error (exit={r.returncode}, "
                f"retry {unclassified_retries}/"
                f"{POLL_UNCLASSIFIED_RETRY_LIMIT}): "
                f"{stderr or output}"
            )
            time.sleep(interval)


def _compose_poll_diagnostic(stdout: str, stderr: str) -> str:
    """Combine GitHub Actions poll stdout and stderr for failure event payloads."""
    parts = [s for s in (stdout, stderr) if s]
    return "\n".join(parts) if parts else ""


# Branch-gate + CI-gate logic lives in deploy_pipeline_gates
# (resolve_flow_gate_branch, _resolve_and_verify_branch,
# _verify_branch_merged, _check_ci_gate).
