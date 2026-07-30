"""Ephemeral deployment verification executor."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from typing import Any, Dict, List, Optional

from yoke_core.domain.deploy_pipeline_reporting import (
    _emit_run_event,
    _resolve_script_dir,
)


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
    executors: Any,
    connect_fn: Any,
    query_scalar_fn: Any,
    sd: Optional[str] = None,
) -> int:
    """Verify a preview unless every member already passed ephemeral QA."""
    sd = sd or _resolve_script_dir()

    all_passed = True
    from yoke_core.domain.qa_constants import browser_requirement_predicate

    conn = connect_fn()
    try:
        for item_id in member_items:
            count = query_scalar_fn(
                conn,
                "SELECT COUNT(*) FROM qa_runs qr "
                "JOIN qa_requirements qreq ON qr.qa_requirement_id = qreq.id "
                "WHERE qreq.item_id = %s AND "
                f"{browser_requirement_predicate('qreq')} "
                "AND qreq.qa_phase = 'verification' AND qr.verdict = 'pass'",
                (item_id,),
            )
            if not count:
                all_passed = False
                break
    finally:
        conn.close()

    if all_passed:
        print(
            "  Skipping ephemeral-verify: all member items already passed "
            "ephemeral QA during conduct"
        )
        return 0

    workflow = config.get("workflow", "")
    if not github_repo:
        print(
            f"Error: no github_repo configured for project '{project}'",
            file=sys.stderr,
        )
        return 1
    if not branch or branch == "null":
        from yoke_core.domain.deploy_pipeline_labels import item_label

        print(
            f"Error: no branch available for {item_label(first_item)} -- cannot "
            "verify ephemeral deploy",
            file=sys.stderr,
        )
        return 1

    from yoke_core.domain.ephemeral_substrate import (
        EphemeralPolicyError,
        load_ephemeral_policy,
    )

    try:
        domain = load_ephemeral_policy(project).preview_domain
    except EphemeralPolicyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not workflow:
        print(
            "Error: ephemeral-verify stage missing 'workflow' field in flow definition",
            file=sys.stderr,
        )
        return 1

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = executors.exec_ephemeral_verify(
                github_repo,
                branch,
                workflow,
                domain,
                "",
                project=project,
            )
    except Exception as exc:  # pragma: no cover
        print(f"Error: exec_ephemeral_verify raised: {exc}", file=sys.stderr)
        return 1

    output = buf.getvalue().strip()
    if output:
        print(output)

    if rc == 0:
        for line in output.split("\n"):
            if line.startswith("EPHEMERAL_URL="):
                _emit_run_event(
                    "DeploymentRunStageCompleted",
                    "completed",
                    {
                        "run_id": run_id,
                        "stage": name,
                        "result": "success",
                        "preview_url": line.split("=", 1)[1],
                    },
                    member_items=member_items,
                    project=project,
                    sd=sd,
                )
                return -3

    return rc


__all__ = ["dispatch_ephemeral_verify"]
