"""Keep agent-selected member plan contracts scoped to their member."""

import json
from collections.abc import Mapping

from yoke_core.domain.deployment_requirement_snapshots import _canonical


def selection_applies_to_member(selection, member):
    """Flow selections apply to every member; a member admission applies only there."""
    owner = selection.get("member_item_id")
    return owner is None or owner == member


def freeze_member_plans(conn, subject, snapshots):
    """Save new member admissions; explicit corrections update existing contracts."""
    from yoke_core.domain.deployment_qa_snapshot_correction import (
        refresh_selected_cases,
    )
    from yoke_core.domain.deployment_qa_snapshot_selection import (
        require_complete_snapshot,
    )

    run_id, member = subject["id"], int(subject["member_item_id"])
    stage = subject["stage"]["name"]
    for snapshot in snapshots:
        if not snapshot.get("selected_by_agent"):
            continue
        require_complete_snapshot(snapshot)
        row = conn.execute(
            "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()
        raw = row[0]
        payload = dict(raw) if isinstance(raw, Mapping) else json.loads(raw)
        plan_id = int(snapshot["plan"]["id"])
        selected = any(
            value.get("stage") == stage
            and int(value["plan"]["id"]) == plan_id
            and selection_applies_to_member(value, member)
            for value in payload.get("selections", [])
        )
        attached = payload.get("item_qa_plan_owners", {}).get(str(plan_id)) is not None
        if selected or attached:
            refresh_selected_cases(
                conn,
                run_id=run_id,
                stage=stage,
                member=member,
                plan_id=plan_id,
                cases=snapshot["cases"],
                allow_added=True,
            )
            continue
        admission = {
            "stage": stage,
            "member_item_id": member,
            "plan": dict(snapshot["plan"]),
            "cases": snapshot["cases"],
            "selected_by_agent": True,
        }
        if "replacement_scopes" in snapshot:
            admission["replacement_scopes"] = snapshot["replacement_scopes"]
        payload.setdefault("selections", []).append(admission)
        conn.execute(
            "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
            (_canonical(payload), run_id),
        )


def keep_carried_plan_pins(flow_snapshot, existing):
    """First composition freeze keeps plan pins a takeover carried for run rows."""
    old = existing if isinstance(existing, Mapping) else json.loads(existing or "{}")
    new = json.loads(flow_snapshot)
    for key in ("item_qa_plan_owners", "plan_groups"):
        if old.get(key):
            new[key] = {**old[key], **new.get(key, {})}
    return _canonical(new)
