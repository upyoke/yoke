"""Atomic explicit corrections to existing private or shared frozen selections."""

import json
from collections.abc import Mapping

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


def selected_plan_owners(
    conn, *, run_id, stage, plan_id, member_item_id=None, shared_target_digest=None
):
    """Lock existing selection owners for one private or exact shared subject."""
    run = conn.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s FOR UPDATE",
        (run_id,),
    ).fetchone()
    if run is None:
        incomplete_snapshot(plan_id, "deployment run is missing")
    shared_source = None
    if shared_target_digest:
        rows = query_rows(
            conn,
            "SELECT execution_target_json FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_stage=%s AND plan_id=%s AND execution_target_digest=%s",
            (run_id, stage, plan_id, shared_target_digest),
        )
        if not rows:
            incomplete_snapshot(plan_id, "shared execution target is missing")
        raw = rows[0]["execution_target_json"]
        target = raw if isinstance(raw, Mapping) else json.loads(str(raw))
        shared_source = target["deployment"]["shared_plan"]["source_revision"]
    candidates = []
    owners = [("deployment_runs", "id=%s", (run_id,), "selections", run)]
    if member_item_id is not None or shared_target_digest:
        members = conn.execute(
            "SELECT item_id,requirement_snapshot FROM deployment_run_items "
            "WHERE run_id=%s "
            + ("" if shared_target_digest else "AND item_id=%s ")
            + "ORDER BY item_id FOR UPDATE",
            (run_id,) if shared_target_digest else (run_id, member_item_id),
        ).fetchall()
        for member in members:
            if shared_target_digest:
                from yoke_core.domain.deployment_qa_shared_plans import (
                    member_group_digests,
                )

                if shared_target_digest not in member_group_digests(
                    conn, run_id, stage, int(member["item_id"])
                ):
                    continue
            owners.append(
                (
                    "deployment_run_items",
                    "run_id=%s AND item_id=%s",
                    (run_id, int(member["item_id"])),
                    "plans",
                    member,
                )
            )
    for table, where, params, field, row in owners:
        raw = row["requirement_snapshot"]
        payload = dict(raw) if isinstance(raw, Mapping) else json.loads(str(raw))
        for index, value in enumerate(payload.get(field, [])):
            if (field == "selections" and value.get("stage") != stage) or int(
                value.get("plan", {}).get("id") or 0
            ) != int(plan_id):
                continue
            require_complete_snapshot(value)
            if (
                shared_target_digest
                and value["plan"]["source_revision"] != shared_source
            ):
                continue
            candidates.append((table, where, params, field, payload, index))
    if not candidates or (
        len(candidates) != 1
        and (
            not shared_target_digest
            or any(value[0] == "deployment_runs" for value in candidates)
        )
    ):
        incomplete_snapshot(plan_id, "selected plan owner is missing or ambiguous")
    if len(candidates) != len({(value[0], value[2]) for value in candidates}):
        incomplete_snapshot(plan_id, "selected plan owner has duplicate contracts")
    return candidates


def refresh_selected_cases(
    conn,
    *,
    run_id,
    stage,
    plan_id,
    member_item_id,
    cases,
    allow_added=False,
    shared_target_digest=None,
):
    """Correct only eligible cases, preserving owner and admission provenance."""
    owners = selected_plan_owners(
        conn,
        run_id=run_id,
        stage=stage,
        plan_id=plan_id,
        member_item_id=member_item_id,
        shared_target_digest=shared_target_digest,
    )
    for owner in owners:
        _refresh_selected_cases(
            conn,
            owner,
            run_id=run_id,
            stage=stage,
            plan_id=plan_id,
            cases=cases,
            allow_added=allow_added,
            shared_target_digest=shared_target_digest,
        )


def _refresh_selected_cases(
    conn, owner, *, run_id, stage, plan_id, cases, allow_added, shared_target_digest
):
    from yoke_core.domain.deployment_requirement_snapshot_format import semantic_row

    table, where, params, field, payload, index = owner
    snapshot = payload[field][index]
    member = (
        params[1]
        if table == "deployment_run_items" and not shared_target_digest
        else None
    )
    replacements = {
        str(case["case_key"]): semantic_row(case, CASE_FIELDS) for case in cases
    }
    from yoke_core.domain.qa_plan_management import _plan_row

    current_plan = semantic_row(dict(_plan_row(conn, plan_id)), PLAN_FIELDS)
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
    from yoke_core.domain.qa_deployment_case_correction_window import (
        determinate_verdict,
    )

    for frozen in snapshot["cases"]:
        key = str(frozen["case_key"])
        if key not in replacements or replacements[key] == frozen:
            continue
        rows = query_rows(
            conn,
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_stage=%s AND plan_id=%s AND plan_case_key=%s "
            "AND deployment_member_item_id IS NOT DISTINCT FROM %s "
            "AND (CAST(%s AS TEXT) IS NULL OR execution_target_digest=%s)",
            (
                run_id,
                stage,
                plan_id,
                key,
                member,
                shared_target_digest,
                shared_target_digest,
            ),
        )
        if any(determinate_verdict(conn, int(row["id"])) == "pass" for row in rows):
            incomplete_snapshot(plan_id, "case already has passed acceptance")
    snapshot["cases"] = [
        replacements.get(str(case["case_key"]), case) for case in snapshot["cases"]
    ]
    if allow_added:
        snapshot["cases"].extend(
            case for key, case in replacements.items() if key not in existing
        )
    require_complete_snapshot(snapshot)
    conn.execute(
        f"UPDATE {table} SET requirement_snapshot=%s WHERE {where}",
        (_canonical(payload), *params),
    )
