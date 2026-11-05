"""Select corrections for failed group cases without moving unrelated pinned work."""

from __future__ import annotations

from yoke_core.domain.qa_requirement_lineage import head_owes_work, rows_by_case
from yoke_core.domain.qa_deployment_case_content_refresh import (
    case_content_digest,
    plan_case_content_digest,
)


def corrected_group_snapshot(conn, subject, target, snapshot):
    """Keep admitted content, taking live edits only for a failed case's retry.

    A correction stays admitted on later retries, even if its plan moves again.
    New keys and edits to pending or passed cases wait for the next release.
    The ordinary content-refresh writer records and settles each replacement.
    """
    from yoke_core.domain.qa_deployment_requirement_identity_schema import (
        shared_group_id,
    )
    from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
    from yoke_core.domain.qa_plan_source_revision import require_candidate_plan

    plan_id = int(subject["shared_plan"]["plan_id"])
    groups = rows_by_case(
        conn,
        run_id=subject["id"],
        stage_name=subject["stage"]["name"],
        member_item_id=None,
        plan_id=plan_id,
        group_id=shared_group_id(target),
    )
    by_key = {}
    for (key, baseline), heads in groups.items():
        by_key.setdefault(key, []).extend(heads)
    failed = {
        key
        for key, heads in by_key.items()
        if any(
            int(head["plan_id"]) == plan_id and head_owes_work(conn, head)
            for head in heads
        )
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
