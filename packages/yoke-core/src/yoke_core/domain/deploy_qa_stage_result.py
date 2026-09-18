"""Stage-result recording for the deployment QA recorder.

Owns ``cmd_record_stage_result`` — the largest single command of the
recorder. It reads/writes qa_requirements, qa_runs, qa_artifacts, and the
deployment_run_qa projection in-process through the ordinary domain
functions, so it inherits whatever database/actor authority the current
execution context (a relayed HTTPS request handler, or a direct local
connection) already carries.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import sys
from typing import Any, Dict, Optional

from yoke_core.domain.db_helpers import connect, query_scalar
from yoke_core.domain.deploy_qa_stage_helpers import (
    resolve_qa_kind_for_stage,
    resolve_stages_json_for_run,
)

_logger = logging.getLogger(__name__)


def cmd_record_stage_result(
    run_id: str,
    stage_name: str,
    verdict: str,
    *,
    raw_result: str = "{}",
    duration_ms: Optional[str] = None,
    workflow_run: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Record a QA run for a deployment stage.

    Returns the qa_run_id on success, or ``None`` when ``stage_name`` is not
    a QA stage — a legitimate no-op. Raises ``RuntimeError`` when a QA
    stage's result could not be recorded, or when the run/flow itself could
    not be resolved at all, so a caller never mistakes a missing run or a
    write failure for quiet success.
    """
    from yoke_core.domain.deployment_runs_qa import cmd_qa_add, cmd_qa_update
    from yoke_core.domain.qa_artifact_ops import cmd_artifact_add
    from yoke_core.domain.qa_execution import cmd_run_add
    from yoke_core.domain.qa_requirements import cmd_requirement_add

    try:
        stages_json = resolve_stages_json_for_run(run_id, db_path=db_path)
    except LookupError as exc:
        raise RuntimeError(
            f"could not resolve flow/stages for run {run_id!r}: {exc}"
        ) from exc
    qa_kind = resolve_qa_kind_for_stage(stages_json, stage_name)

    if not qa_kind:
        _logger.debug("Stage %r is not a QA stage; no verdict to record", stage_name)
        return None

    conn = connect(db_path)
    try:
        # Find existing requirement
        req_id = query_scalar(
            conn,
            "SELECT id FROM qa_requirements "
            "WHERE deployment_run_id=%s AND qa_kind=%s AND qa_phase='post_deploy' LIMIT 1",
            (run_id, qa_kind),
        )

        if not req_id:
            print(
                f"Warning: no qa_requirement found for run={run_id} kind={qa_kind} — seeding now",
                file=sys.stderr,
            )
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    req_id = cmd_requirement_add(
                        db_path=db_path,
                        deployment_run_id=run_id,
                        deployment_stage=stage_name,
                        qa_kind=qa_kind,
                        qa_phase="post_deploy",
                        blocking_mode="blocking",
                        requirement_source="flow_derived",
                        success_policy="Workflow completes with conclusion=success",
                    )
            except SystemExit as exc:
                raise RuntimeError(
                    f"failed to seed qa_requirement for stage {stage_name!r} "
                    f"(exit {exc.code})"
                ) from exc
            cmd_qa_add(run_id, stage_name, "flow_default", 1, db_path=db_path)

        # Read success_policy
        success_policy = (
            query_scalar(
                conn,
                "SELECT COALESCE(success_policy, '') FROM qa_requirements WHERE id=%s",
                (req_id,),
            )
            or ""
        )
    finally:
        conn.close()

    # Map verdict
    verdict_map = {
        "pass": "pass",
        "success": "pass",
        "fail": "fail",
        "failure": "fail",
        "error": "error",
    }
    run_verdict = verdict_map.get(verdict, verdict)

    # Build enriched result JSON
    try:
        base = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        base = {}
    base["stage"] = stage_name
    base["run_id"] = run_id
    base["qa_kind"] = qa_kind
    if workflow_run:
        base["workflow_run_id"] = workflow_run
    if success_policy:
        base["success_policy"] = success_policy
    enriched_result = json.dumps(base)

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            qa_run_id = cmd_run_add(
                db_path=db_path,
                requirement_id=int(req_id),
                performed_by="github-actions",
                qa_kind=qa_kind,
                verdict=run_verdict,
                raw_result=enriched_result,
                duration_ms=int(duration_ms) if duration_ms else None,
            )
    except SystemExit as exc:
        raise RuntimeError(
            f"failed to record qa_run for stage {stage_name!r} (exit {exc.code})"
        ) from exc

    # Attach log artifact
    artifact_meta: Dict[str, Any] = {"stage": stage_name, "qa_kind": qa_kind}
    if workflow_run:
        artifact_meta["workflow_run_id"] = workflow_run

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_artifact_add(
                db_path=db_path,
                run_id=qa_run_id,
                artifact_type="log",
                content_type="application/json",
                metadata=json.dumps(artifact_meta),
            )
    except SystemExit as exc:
        raise RuntimeError(
            f"failed to attach qa_run artifact for stage {stage_name!r} "
            f"(exit {exc.code})"
        ) from exc

    # Update deployment_run_qa projection
    drqa_status = "passed" if run_verdict == "pass" else "failed"
    qa_update_error = cmd_qa_update(run_id, stage_name, drqa_status, db_path=db_path)
    if qa_update_error:
        raise RuntimeError(
            "failed to update deployment_run_qa projection for stage "
            f"{stage_name!r}: {qa_update_error}"
        )

    print(
        f"Recorded QA: stage={stage_name} verdict={run_verdict} req={req_id} run={qa_run_id} projection={drqa_status}"
    )
    return str(qa_run_id)
