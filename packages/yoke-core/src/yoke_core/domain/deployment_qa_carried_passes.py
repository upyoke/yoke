"""Read passed member cases while successor acceptance is still pending."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_target_reads import (
    _decode_stored_target,
    _latest_ready_receipt_id,
)
from yoke_core.domain.qa_latest_execution import latest_executions
from yoke_core.domain.qa_requirement_pass_currency import passing_requirements_for_rows


def fully_passed_member_cases(
    conn: Any, run_id: str, item_ids: Sequence[int], *, plan_id: int | None = None
) -> dict[int, list[dict]]:
    """Members with a nonempty cohort and current proof for every live case."""
    if not item_ids:
        return {}
    plan_filter = " AND plan_id=%s" if plan_id is not None else ""
    params = (run_id, sorted(set(item_ids)))
    rows = query_rows(
        conn,
        "SELECT * FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=ANY(%s) AND method_id IS NOT NULL "
        "AND waived_at IS NULL AND superseded_at IS NULL "
        "AND superseded_by_requirement_id IS NULL AND retracted_at IS NULL"
        f"{plan_filter} ORDER BY id",
        params + ((plan_id,) if plan_id is not None else ()),
    )
    if not rows:
        return {}
    attempts = latest_executions(conn, [int(row["id"]) for row in rows])
    passed = passing_requirements_for_rows(conn, rows, attempts)
    by_member = defaultdict(list)
    for row in rows:
        by_member[int(row["deployment_member_item_id"])].append(row)
    return {
        member: cases
        for member, cases in by_member.items()
        if all(int(case["id"]) in passed for case in cases)
    }


def carried_plan_passes(
    conn: Any, run_id: str, item_id: int, plan_id: int, stage: dict
) -> list[int]:
    """Keep a recorded pass visible while it still answers the successor."""
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
    from yoke_core.domain.deployment_qa_takeover_identity import inherited_target
    from yoke_core.domain.deployment_qa_target_continuity import same_destination

    rows = fully_passed_member_cases(conn, run_id, [item_id], plan_id=plan_id).get(
        item_id, []
    )
    stored = [_decode_stored_target(row["execution_target_json"]) for row in rows]
    if not stored or any(target is None for target in stored):
        return []
    if not any(inherited_target(conn, run_id, target) for target in stored):
        return []

    # Before a ready receipt, the moved cases still answer the inherited
    # destination. Once a receipt resolves the current destination, use the
    # same comparison as materialization, even if no rebind has happened yet.
    source = (stage.get("target") or {}).get("source_stage")
    if source and _latest_ready_receipt_id(conn, run_id=run_id, source_stage=source):
        try:
            subject = deployment_qa_stage_subject(
                conn,
                run_id=run_id,
                stage_name=stage["name"],
                member_item_id=item_id,
                require_active=False,
            )
            current = deployment_qa_execution_target(conn, subject)
        except ValueError:
            return []  # A destination that cannot be resolved cannot carry proof.
        if any(not same_destination(target, current) for target in stored):
            return []
    return [int(row["id"]) for row in rows]
