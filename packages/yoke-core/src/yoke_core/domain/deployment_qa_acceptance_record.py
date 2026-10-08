"""Record aggregate QA against the actual completed scoped execution.

The stage gate delegates this write so its subject selection stays separate
from proof stamping. No other aggregate acceptance writer is applicable.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
)


def record_acceptance(
    conn: Any,
    *,
    requirement_id: int,
    execution_id: str,
    verdict: str,
    reason: str,
) -> int:
    from yoke_core.domain.qa_run_verdict_record import insert_qa_run

    from yoke_core.domain.qa_requirement_pass_currency import (
        stamp_executed_method_config,
    )

    execution = conn.execute(
        "SELECT execution_target_digest FROM qa_plan_executions WHERE id=%s",
        (execution_id,),
    ).fetchone()
    if execution is None:
        raise ValueError(
            "stage_acceptance_execution_missing: acceptance must identify its actual execution"
        )
    raw = stamp_executed_method_config(
        json.dumps({"execution_id": execution_id}, sort_keys=True),
        None,
        execution_target_digest=execution["execution_target_digest"],
    )
    now = iso8601_now()
    return insert_qa_run(
        conn,
        qa_requirement_id=requirement_id,
        performed_by="agent",
        qa_kind=DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
        verdict=verdict,
        verdict_reason=reason,
        raw_result=raw,
        started_at=now,
        completed_at=now,
        created_at=now,
    ).run_id
