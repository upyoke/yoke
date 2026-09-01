"""Deployment-stage failure recording and terminal-cause reporting."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, List, Optional

from yoke_core.domain import deploy_pipeline_poll_authority as poll_authority
from yoke_core.domain import deploy_pipeline_reporting as reporting
from yoke_core.domain import deploy_pipeline_run_updates as run_updates
from yoke_core.domain import deploy_qa_recorder


EXIT_STAGE_FAILED = 1


def _failure_trace_command(run_id: str) -> subprocess.CompletedProcess:
    local_authority = os.environ.get(
        poll_authority.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
        "",
    ).strip()
    explicit_relay = os.environ.get(
        poll_authority.GITHUB_ACTIONS_RELAY_ENV,
        "",
    ).strip()
    if explicit_relay and local_authority:
        return subprocess.CompletedProcess(
            args=[],
            returncode=4,
            stdout="",
            stderr="GitHub Actions authority is ambiguous",
        )
    if local_authority not in ("", "1"):
        return subprocess.CompletedProcess(
            args=[],
            returncode=4,
            stdout="",
            stderr=(f"{poll_authority.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV} must be 1"),
        )
    relay_env, relay_source = poll_authority.resolve_status_relay_env()
    if local_authority:
        relay_env, relay_source = None, ""
    command = [
        sys.executable,
        "-m",
        "yoke_cli.main",
    ]
    if relay_env:
        command.extend(["--env", relay_env])
    elif (
        os.environ.get(
            poll_authority.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
            "",
        ).strip()
        != "1"
    ):
        return subprocess.CompletedProcess(
            args=command,
            returncode=4,
            stdout="",
            stderr=(
                "no GitHub Actions read authority is selected; set "
                f"{poll_authority.GITHUB_ACTIONS_RELAY_ENV}=<https-env> "
                "or use attended local authority"
            ),
        )
    command.extend(["deployment-runs", "failure-trace", run_id])
    try:
        completed = reporting._run_cmd(command, timeout=180)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout="",
            stderr="failure trace timed out after 180 seconds",
        )
    except OSError as exc:
        return subprocess.CompletedProcess(
            args=command,
            returncode=4,
            stdout="",
            stderr=f"failure trace command could not start: {exc}",
        )
    if relay_env and completed.returncode != 0 and relay_source:
        detail = (completed.stderr or completed.stdout or "").strip()
        completed = subprocess.CompletedProcess(
            args=completed.args,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=f"{relay_source} ({relay_env}): {detail}",
        )
    return completed


def _report_failure_trace(run_id: str) -> None:
    trace = _failure_trace_command(run_id)
    if trace.stdout.strip():
        print(trace.stdout.rstrip(), file=sys.stderr)
    if trace.returncode == 0:
        return
    detail = (trace.stderr or trace.stdout or "").strip() or "no diagnostic"
    print(
        f"Failure trace stopped before the dispatch chain could be resolved: {detail}",
        file=sys.stderr,
    )
    print(
        "Recovery: restore the named control-plane/GitHub read authority, then "
        f"run `yoke deployment-runs failure-trace {run_id}`.",
        file=sys.stderr,
    )


def fail_pipeline_stage(
    *,
    exit_code: int,
    diagnostic: str,
    stage_name: str,
    run_id: str,
    flow_id: str,
    member_items: List[str],
    project: str,
    sd: Optional[str],
    emit_event: Callable[..., None],
) -> int:
    """Record one failed stage, explain its terminal cause, and return 1."""
    if diagnostic:
        print(f"Step runner diagnostic: {diagnostic}", file=sys.stderr)
    context = {
        "run_id": run_id,
        "stage": stage_name,
        "result": "failed",
        "exit_code": exit_code,
    }
    if diagnostic:
        context["step_runner_diagnostic"] = diagnostic
    emit_event(
        "DeploymentRunStageFailed",
        "failed",
        context,
        member_items=member_items,
        project=project,
        sd=sd,
    )
    reporting._set_deploy_stage(
        f"{stage_name}-failed",
        run_id,
        member_items,
        sd=sd,
    )
    deploy_qa_recorder.cmd_record_stage_result(
        run_id,
        stage_name,
        "fail",
        script_dir=sd,
    )
    run_updates.update_run_field(run_id, "status", "failed")
    emit_event(
        "DeploymentRunFailed",
        "failed",
        {"run_id": run_id, "stage": stage_name, "flow": flow_id},
        member_items=member_items,
        project=project,
        sd=sd,
    )
    _report_failure_trace(run_id)
    print(
        f"Error: stage '{stage_name}' failed (exit code: {exit_code})",
        file=sys.stderr,
    )
    return EXIT_STAGE_FAILED


__all__ = ["EXIT_STAGE_FAILED", "fail_pipeline_stage"]
