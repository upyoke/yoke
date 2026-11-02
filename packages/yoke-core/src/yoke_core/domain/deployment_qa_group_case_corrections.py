"""Select corrections for failed group cases without moving unrelated pinned work."""

from __future__ import annotations

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_deployment_case_content_refresh import (
    base_case_key,
    carried_by_declared_replacement,
    case_content_digest,
    plan_case_content_digest,
)
from yoke_core.domain.qa_latest_execution import latest_verdict_executions
from yoke_core.domain.qa_obligation_settlement import obligation_settled


def corrected_group_snapshot(conn, subject, target, snapshot):
    """Keep admitted content, taking live edits only for a failed case's retry.

    A correction stays admitted on later retries, even if its plan moves again.
    New keys and edits to pending or passed cases wait for the next release.
    The ordinary content-refresh writer records and settles each replacement.
    """
    from yoke_core.domain.qa_execution_environment_target import target_digest
    from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
    from yoke_core.domain.qa_plan_source_revision import require_candidate_plan

    plan_id = int(subject["shared_plan"]["plan_id"])
    rows = query_rows(
        conn,
        "SELECT id,plan_case_key,method_id,method_config,instructions,expected_outcome,"
        "replacement_requirement_id,waived_at,superseded_by_requirement_id,retracted_at "
        "FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND deployment_member_item_id IS NULL AND plan_id=%s "
        "AND execution_target_digest=%s ORDER BY id",
        (subject["id"], subject["stage"]["name"], plan_id, target_digest(target)),
    )
    by_key = {}
    for row in rows:
        by_key.setdefault(base_case_key(row["plan_case_key"]), []).append(row)
    attempts = latest_verdict_executions(conn, [int(row["id"]) for row in rows])
    failed = {
        key
        for key, copies in by_key.items()
        if attempts.get(int(copies[-1]["id"]), {}).get("verdict") == "fail"
        and not obligation_settled(copies[-1])
        and not carried_by_declared_replacement(conn, copies)
    }
    live = (
        _plan_snapshot(conn, plan_id, project_id=int(subject["member_project_id"]))
        if failed
        else None
    )
    current = {case["case_key"]: case for case in live["cases"]} if live else {}
    cases = []
    for pinned in snapshot["cases"]:
        key = pinned["case_key"]
        copies = by_key.get(key)
        case = dict(pinned)
        if copies:
            # A previous correction may have changed the registered method.
            case.pop("config_contract_id", None)
            case.update(
                {
                    field: copies[-1][field]
                    for field in (
                        "method_id",
                        "method_config",
                        "instructions",
                        "expected_outcome",
                    )
                }
            )
        if key in failed and key in current:
            corrected = current[key]
            if plan_case_content_digest(conn, corrected) != case_content_digest(case):
                require_candidate_plan(conn, live["plan"], str(subject["id"]))
                case = corrected
        cases.append(case)
    return {**snapshot, "cases": cases}
