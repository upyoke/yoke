"""Protected landed CI receipts retain proof when snapshot rules tighten."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.item_merge_receipt_document import landing_shas
from yoke_core.domain.qa_merging_identity import queue_batch_covers_receipt
from yoke_core.domain.qa_plan_execution_store import marker


def landed_receipt_proves_unchanged_requirement(
    conn: Any, requirement_id: int, run: Mapping[str, Any]
) -> bool:
    """Read durable merge authority, never infer it from a green or telemetry.

    The caller already checked the latest actual pass and any recorded config
    and digest. Only an uncorrected verification CI requirement may use its
    protected batch receipt instead of snapshots the old runner never wrote.
    A different landing, target correction, or config correction invalidates it.
    """
    from yoke_core.domain.qa_requirement_pass_currency import (
        executable_method_config,
        method_config_was_corrected,
    )

    row = query_one(
        conn,
        f"SELECT * FROM qa_requirements WHERE id={marker(conn)}",
        (int(requirement_id),),
    )
    if row is None:
        return False
    requirement = dict(row)
    if (
        run.get("performed_by") != "ci_run"
        or requirement.get("runner_id") != "ci_run"
        or requirement.get("method_id") != "command-ci"
        or requirement.get("qa_phase") != "verification"
        or not requirement.get("item_id")
        or requirement.get("deployment_run_id")
        or requirement.get("target_env")
        or requirement.get("rebound_at")
        or method_config_was_corrected(requirement.get("method_config"))
        or not executable_method_config(requirement.get("method_config")).get(
            "ci_workflow"
        )
    ):
        return False
    return queue_batch_covers_receipt(
        [run.get("raw_result")], landing_shas(conn, int(requirement["item_id"]))
    )
