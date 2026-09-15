"""Stage helpers for the deployment QA recorder.

Pure helpers shared by ``deploy_qa_recorder`` and ``deploy_qa_stage_result``:

* ``resolve_stages_json_for_run`` reads a run's flow and that flow's stage
  list in-process, against whichever database serves the current execution
  context (the relayed HTTPS request's bound connection, or a direct local
  one) — no subprocess, no filesystem/checkout assumption.
* parsing flow stage JSON to extract QA-relevant entries,
* resolving the ``qa_kind`` for a single stage by name.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from yoke_core.domain.deployment_flow_policy import QA_STEP_RUNNER, STAGE_KIND_QA


def resolve_stages_json_for_run(run_id: str, *, db_path: Optional[str] = None) -> str:
    """Return the raw stages JSON for a run's flow.

    Reads the run's ``flow`` field and that flow's ``stages`` column
    in-process through the ordinary domain query functions, so the caller
    inherits whatever database authority (bound DSN, actor identity) the
    current execution context already carries.

    Raises ``LookupError`` when the run or its flow cannot be resolved —
    distinct from a readable flow whose stages simply don't include the
    stage being asked about, which is the caller's own legitimate no-op to
    interpret. Collapsing "unreadable" into "empty" would let a missing
    run or flow read as a stage that quietly isn't QA-relevant.
    """
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_runs_crud_query import cmd_get
    from yoke_core.domain.flow import cmd_stages

    flow_id = cmd_get(run_id, "flow", db_path=db_path)
    if not flow_id:
        raise LookupError(f"deployment run {run_id!r} not found or has no flow")
    conn = connect(db_path)
    try:
        return cmd_stages(conn, flow_id)
    finally:
        conn.close()


def parse_stages_qa(stages_json: str) -> List[Dict[str, str]]:
    """Parse flow stages JSON and return QA-relevant entries.

    A stage is QA-relevant if it has an explicit ``qa_kind`` field or
    its name contains ``smoke``.
    """
    stages = json.loads(stages_json)
    qa_stages: List[Dict[str, str]] = []
    for s in stages:
        if (
            s.get("stage_kind") == STAGE_KIND_QA
            or s.get("step_runner") == QA_STEP_RUNNER
        ):
            # Scoped release QA materializes and settles through
            # qa_requirements/qa_runs.  The legacy deployment_run_qa table is
            # only a projection for schema-1 flow checks, never a second
            # authority for advanced stage acceptance.
            continue
        name = s.get("name", "")
        qa_kind = s.get("qa_kind", "")
        success_policy = s.get("success_policy", "")
        if not qa_kind and "smoke" in name:
            qa_kind = "smoke"
        if qa_kind:
            if not success_policy:
                success_policy = "Workflow completes with conclusion=success"
            qa_stages.append(
                {
                    "name": name,
                    "qa_kind": qa_kind,
                    "success_policy": success_policy,
                }
            )
    return qa_stages


def resolve_qa_kind_for_stage(stages_json: str, stage_name: str) -> str:
    """Resolve the qa_kind for a named stage from the flow config."""
    try:
        stages = json.loads(stages_json)
    except (json.JSONDecodeError, TypeError):
        stages = []
    for s in stages:
        if s.get("name") == stage_name:
            if (
                s.get("stage_kind") == STAGE_KIND_QA
                or s.get("step_runner") == QA_STEP_RUNNER
            ):
                return ""
            qk = s.get("qa_kind", "")
            if not qk and "smoke" in stage_name:
                qk = "smoke"
            return qk
    # Fallback: infer from name
    if "smoke" in stage_name:
        return "smoke"
    return ""
