"""Atomic explicit corrections to a run's frozen flow-declared plan selection.

Flow-declared plans freeze on the run's ``selections``, one per stage and
plan. A plan group pins its plan in ``plan_groups`` and is never refreshed:
an edited plan runs on the next release, so it has no owner here.
"""

import json
from collections.abc import Mapping

from yoke_core.domain.deployment_runs_lock import lock_run
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_requirement_snapshot_format import (
    CASE_FIELDS,
    PLAN_FIELDS,
)
from yoke_core.domain.deployment_requirement_snapshots import _canonical
from yoke_core.domain.deployment_qa_snapshot_selection import (
    incomplete_snapshot,
    require_complete_snapshot,
)


def selected_plan_owners(conn, *, run_id, stage, plan_id):
    """Lock the run and return its one frozen selection of this plan and stage.

    Returns ``(payload, index)``: the run's decoded requirement snapshot and
    the position of the selection in its ``selections``.
    """
    lock_run(conn, str(run_id))
    run = conn.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s FOR UPDATE",
        (run_id,),
    ).fetchone()
    if run is None:
        incomplete_snapshot(plan_id, "deployment run is missing")
    raw = run["requirement_snapshot"]
    payload = dict(raw) if isinstance(raw, Mapping) else json.loads(str(raw))
    candidates = []
    for index, value in enumerate(payload.get("selections", [])):
        if value.get("stage") != stage:
            continue
        if int(value.get("plan", {}).get("id") or 0) != int(plan_id):
            continue
        require_complete_snapshot(value)
        candidates.append(index)
    if len(candidates) != 1:
        incomplete_snapshot(plan_id, "selected plan owner is missing or ambiguous")
    return payload, candidates[0]


def _case_passed(conn, *, run_id, stage, plan_id, key):
    """Whether a run-wide copy of this case passed acceptance."""
    from yoke_core.domain.qa_deployment_case_correction_window import (
        determinate_verdict,
    )

    rows = query_rows(
        conn,
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND plan_id=%s AND plan_case_key=%s "
        "AND deployment_member_item_id IS NULL",
        (run_id, stage, plan_id, key),
    )
    return any(determinate_verdict(conn, int(row["id"])) == "pass" for row in rows)


def refresh_selected_cases(conn, *, run_id, stage, plan_id, cases, allow_added=False):
    """Correct only eligible cases, preserving the selection's admission provenance."""
    from yoke_core.domain.deployment_requirement_snapshot_format import semantic_row
    from yoke_core.domain.qa_plan_management import _plan_row

    payload, index = selected_plan_owners(
        conn, run_id=run_id, stage=stage, plan_id=plan_id
    )
    current_plan = semantic_row(dict(_plan_row(conn, plan_id)), PLAN_FIELDS)
    snapshot = payload["selections"][index]
    before = _canonical(payload)
    replacements = {
        str(case["case_key"]): semantic_row(case, CASE_FIELDS) for case in cases
    }
    for case in replacements.values():
        for policy_field in ("success_policy_id", "success_policy_params"):
            if (
                case[policy_field] is None
                and current_plan[policy_field] != snapshot["plan"][policy_field]
            ):
                case[policy_field] = current_plan[policy_field]
    existing = {str(case["case_key"]) for case in snapshot["cases"]}
    if replacements.keys() - existing and not allow_added:
        incomplete_snapshot(plan_id, "corrected case has no admitted selection")
    for frozen in snapshot["cases"]:
        key = str(frozen["case_key"])
        if key not in replacements or replacements[key] == frozen:
            continue
        if _case_passed(conn, run_id=run_id, stage=stage, plan_id=plan_id, key=key):
            incomplete_snapshot(plan_id, "case already has passed acceptance")
    snapshot["cases"] = [
        replacements.get(str(case["case_key"]), case) for case in snapshot["cases"]
    ]
    if allow_added:
        snapshot["cases"].extend(
            case for key, case in replacements.items() if key not in existing
        )
    require_complete_snapshot(snapshot)
    after = _canonical(payload)
    if after != before:
        conn.execute(
            "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
            (after, run_id),
        )
