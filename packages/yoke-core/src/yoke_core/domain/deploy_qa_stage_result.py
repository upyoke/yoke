"""Stage-result recording for the deployment QA recorder.

Owns ``cmd_record_stage_result`` — the largest single command of the
recorder. The implementation looks up the dispatch helpers and the
script-dir resolver via the ``deploy_qa_recorder`` module at call time
so that test monkeypatches against ``deploy_qa_recorder._dispatch_*``
remain authoritative even though the function lives here.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from yoke_core.domain.db_helpers import connect, query_scalar
from yoke_core.domain.deploy_qa_stage_helpers import resolve_qa_kind_for_stage


def cmd_record_stage_result(
    run_id: str,
    stage_name: str,
    verdict: str,
    *,
    raw_result: str = "{}",
    duration_ms: Optional[str] = None,
    workflow_run: Optional[str] = None,
    db_path: Optional[str] = None,
    script_dir: Optional[str] = None,
) -> Optional[str]:
    """Record a QA run for a deployment stage.

    Returns the qa_run_id on success, or None on failure.
    """
    # Resolve dispatch helpers via the orchestrator module at call time so
    # ``monkeypatch.setattr(deploy_qa_recorder, "_dispatch_db_router", ...)``
    # remains authoritative for callers of this function.
    from yoke_core.domain import deploy_qa_recorder as _recorder

    sd = script_dir or _recorder._resolve_script_dir()

    # Resolve qa_kind from flow config
    flow_id = _recorder._dispatch_db_router("runs", "get", run_id, "flow", script_dir=sd)
    stages_json = _recorder._dispatch_flow_domain("stages", flow_id, script_dir=sd) if flow_id else ""
    qa_kind = resolve_qa_kind_for_stage(stages_json, stage_name)

    if not qa_kind:
        print(f"Stage '{stage_name}' is not a QA stage — nothing to record")
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
            print(f"Warning: no qa_requirement found for run={run_id} kind={qa_kind} — seeding now",
                  file=sys.stderr)
            req_id_str = _recorder._dispatch_db_router(
                "qa", "requirement-add",
                "--deployment-run-id", run_id,
                "--qa-kind", qa_kind,
                "--qa-phase", "post_deploy",
                "--blocking-mode", "blocking",
                "--requirement-source", "flow_derived",
                "--success-policy", "Workflow completes with conclusion=success",
                script_dir=sd,
            )
            if not req_id_str:
                print(f"Error: failed to seed qa_requirement for stage '{stage_name}'", file=sys.stderr)
                return None
            req_id = req_id_str
            _recorder._dispatch_db_router("runs", "qa-add", run_id, stage_name, "flow_default", "1", script_dir=sd)

        # Read success_policy
        success_policy = query_scalar(
            conn,
            "SELECT COALESCE(success_policy, '') FROM qa_requirements WHERE id=%s",
            (req_id,),
        ) or ""
    finally:
        conn.close()

    # Map verdict
    verdict_map = {"pass": "pass", "success": "pass", "fail": "fail", "failure": "fail", "error": "error"}
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

    # Record qa_run via CLI
    run_add_args = [
        "qa", "run-add",
        "--requirement-id", str(req_id),
        "--executor-type", "github-actions",
        "--qa-kind", qa_kind,
        "--verdict", run_verdict,
        "--raw-result", enriched_result,
    ]
    if duration_ms:
        run_add_args += ["--duration-ms", duration_ms]

    qa_run_id = _recorder._dispatch_db_router(*run_add_args, script_dir=sd)
    if not qa_run_id:
        print(f"Error: failed to record qa_run for stage '{stage_name}'", file=sys.stderr)
        return None

    # Attach log artifact
    artifact_meta: Dict[str, Any] = {"stage": stage_name, "qa_kind": qa_kind}
    if workflow_run:
        artifact_meta["workflow_run_id"] = workflow_run

    _recorder._dispatch_db_router(
        "qa", "artifact-add",
        "--run-id", qa_run_id,
        "--artifact-type", "log",
        "--content-type", "application/json",
        "--metadata", json.dumps(artifact_meta),
        script_dir=sd,
    )

    # Update deployment_run_qa projection
    drqa_status = "passed" if run_verdict == "pass" else "failed"
    _recorder._dispatch_db_router("runs", "qa-update", run_id, stage_name, drqa_status, script_dir=sd)

    print(f"Recorded QA: stage={stage_name} verdict={run_verdict} req={req_id} run={qa_run_id} projection={drqa_status}")
    return qa_run_id
