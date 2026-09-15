"""Ephemeral deployment verification step runner."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from typing import Any, Dict, List, Optional

from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain.deploy_pipeline_events import emit_run_event as _emit_run_event
from yoke_core.domain.deploy_pipeline_reporting import _resolve_script_dir


def dispatch_ephemeral_verify(
    config: Dict[str, Any],
    *,
    name: str,
    run_id: str,
    member_items: List[str],
    github_repo: str,
    project: str,
    branch: str,
    first_item: str,
    first_item_label: str,
    step_runners: Any,
    sd: Optional[str] = None,
) -> tuple[int, str]:
    """Verify a preview unless every member already passed ephemeral QA.

    Returns ``(exit_code, preview_url)``; ``preview_url`` is populated only on
    a successful verification so a durable stage receipt can record the exact
    observed target a later QA stage reads.
    """
    sd = sd or _resolve_script_dir()

    try:
        all_passed = control_plane.ephemeral_qa_ready(run_id)
    except control_plane.DeploymentControlPlaneError as exc:
        print(f"Error: could not read ephemeral QA readiness: {exc}", file=sys.stderr)
        return 1, ""

    if all_passed:
        print(
            "  Skipping ephemeral-verify: all member items already passed "
            "ephemeral QA during conduct"
        )
        return 0, ""

    workflow = config.get("workflow", "")
    if not github_repo:
        print(
            f"Error: no github_repo configured for project '{project}'",
            file=sys.stderr,
        )
        return 1, ""
    if not branch or branch == "null":
        print(
            f"Error: no branch available for {first_item_label or first_item} -- cannot "
            "verify ephemeral deploy",
            file=sys.stderr,
        )
        return 1, ""

    from yoke_core.domain.ephemeral_substrate import (
        EphemeralPolicyError,
        load_ephemeral_policy,
    )

    try:
        domain = load_ephemeral_policy(project).preview_domain
    except EphemeralPolicyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1, ""
    if not workflow:
        print(
            "Error: ephemeral-verify stage missing 'workflow' field in flow definition",
            file=sys.stderr,
        )
        return 1, ""

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = step_runners.exec_ephemeral_verify(
                github_repo,
                branch,
                workflow,
                domain,
                "",
                project=project,
            )
    except Exception as exc:  # pragma: no cover
        print(f"Error: exec_ephemeral_verify raised: {exc}", file=sys.stderr)
        return 1, ""

    output = buf.getvalue().strip()
    if output:
        print(output)

    if rc == 0:
        for line in output.split("\n"):
            if line.startswith("EPHEMERAL_URL="):
                preview_url = line.split("=", 1)[1]
                _emit_run_event(
                    "DeploymentRunStageCompleted",
                    "completed",
                    {
                        "run_id": run_id,
                        "stage": name,
                        "result": "success",
                        "preview_url": preview_url,
                    },
                    member_items=member_items,
                    project=project,
                    sd=sd,
                )
                return -3, preview_url

    return rc, ""


__all__ = ["dispatch_ephemeral_verify"]
