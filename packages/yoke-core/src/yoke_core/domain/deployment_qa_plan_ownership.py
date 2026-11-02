"""Pin item-owned versus driver-owned post-deploy plans at item QA entry."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows

OWNERS = "item_qa_plan_owners"


def _snapshot(conn: Any, run_id: str) -> dict:
    row = conn.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s", (str(run_id),)
    ).fetchone()
    raw = row[0] if row is not None else None
    return dict(raw) if isinstance(raw, Mapping) else json.loads(raw or "{}")


def plan_owners(conn: Any, run_id: str) -> dict[int, int | None]:
    """An item id owns a single-member plan; None assigns it to the driver.

    Before entry, previews classify the live attachments without writing.
    Plans first attached after entry are classified once on the next dispatch.
    Existing plan ownership never changes with later attachments or removals.
    """
    from yoke_core.domain.deployment_qa_plan_groups import attached_plans, run_groups
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    def read():
        owners = {
            int(plan): owner
            for plan, owner in _snapshot(conn, run_id).get(OWNERS, {}).items()
        }
        # Existing groups retain their driver ownership across rollout and takeover.
        for group in run_groups(conn, run_id):
            owners.setdefault(group.plan_id, None)
        for plan, members in attached_plans(conn, run_id).items():
            owners.setdefault(plan, members[0] if len(members) == 1 else None)
        return owners

    return presentation_read(conn, ("item_qa_plan_owners", str(run_id)), read)


def freeze_plan_owners(conn: Any, run_id: str) -> None:
    """Persist ownership under the caller's run lock; never commit here."""
    from yoke_core.domain.deployment_qa_presentation_reads import uncached_presentation

    snapshot = _snapshot(conn, run_id)
    with uncached_presentation():
        owners = {str(plan): owner for plan, owner in plan_owners(conn, run_id).items()}
    if snapshot.get(OWNERS) == owners:
        return
    snapshot[OWNERS] = owners
    from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot

    pinned = snapshot.setdefault("plan_groups", {})
    for plan, owner in owners.items():
        if owner is not None and plan not in pinned:
            project = conn.execute(
                "SELECT project_id FROM qa_plans WHERE id=%s", (int(plan),)
            ).fetchone()
            selected = _plan_snapshot(
                conn, int(plan), project_id=int(project[0]), lock_plan=False
            )
            pinned[plan] = {"plan": dict(selected["plan"]), "cases": selected["cases"]}
    conn.execute(
        "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
        (json.dumps(snapshot, sort_keys=True, separators=(",", ":")), str(run_id)),
    )


def freeze_stage_owners(conn: Any, run_id: str, stage_name: str) -> None:
    """Stage entry already holds the run row lock through its stage update."""
    row = conn.execute(
        "SELECT f.stages FROM deployment_runs r JOIN deployment_flows f ON f.id=r.flow "
        "WHERE r.id=%s",
        (str(run_id),),
    ).fetchone()
    if row is None:
        return
    stages = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    if any(
        stage.get("name") == stage_name and stage.get("scope") == "item"
        for stage in stages or []
    ):
        freeze_plan_owners(conn, run_id)


def member_plan_ids(conn: Any, run_id: str, item_id: int) -> set[int]:
    """The attached plans that execute as this member's own QA."""
    from yoke_core.domain.deployment_qa_member_plans import member_plan_ids as owed

    owners = plan_owners(conn, run_id)
    return {
        plan for plan in owed(conn, item_id, run_id) if owners.get(plan) is not None
    }


def member_plan_credited(conn: Any, run_id: str, item_id: int, plan_id: int) -> bool:
    """Require this plan's member-bound cases and accepted member QA."""
    from yoke_core.domain.deployment_qa_run_acceptance import current_item_qa

    if plan_owners(conn, run_id).get(plan_id) is None:
        return False
    rows = conn.execute(
        "SELECT DISTINCT deployment_stage FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s AND plan_id=%s AND retracted_at IS NULL",
        (str(run_id), int(item_id), int(plan_id)),
    ).fetchall()
    return bool(rows) and all(
        (
            standing := current_item_qa(
                conn, run_id=run_id, item_id=item_id, current_stage=str(row[0])
            )
        )
        is not None
        and standing.accepted
        for row in rows
    )


def plan_only_members(conn: Any, run_id: str, item_ids: Any) -> set[int]:
    """Members whose item QA is only plans: plan groups answer them, no holder runs."""
    from yoke_core.domain.deployment_qa_member_plans import members_plan_ids

    rows = query_rows(
        conn,
        "SELECT item_id,requirement_snapshot FROM deployment_run_items "
        "WHERE run_id=%s AND item_id=ANY(%s)",
        (str(run_id), sorted({int(item) for item in item_ids})),
    )
    owed = members_plan_ids(conn, (int(row["item_id"]) for row in rows), str(run_id))
    found = set()
    for row in rows:
        member = int(row["item_id"])
        snapshot = row["requirement_snapshot"] or {}
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        own = [
            r
            for r in snapshot.get("requirements") or ()
            if isinstance(r, Mapping)
            and r.get("plan_id") is None
            and r.get("qa_phase") == "post_deploy"
        ]
        from yoke_core.domain.deployment_qa_plan_ownership import member_plan_ids

        if not own and owed[member] and not member_plan_ids(conn, run_id, member):
            found.add(member)
    return found


def transfer_plan_owners(conn: Any, old_id: str, new_id: str) -> None:
    """Keep already-pinned ownership and cases with inherited member QA."""
    old, new = _snapshot(conn, old_id), _snapshot(conn, new_id)
    owners = new.setdefault(OWNERS, {})
    for plan, owner in old.get(OWNERS, {}).items():
        owners.setdefault(plan, owner)
        if owner is not None and plan in (old.get("plan_groups") or {}):
            new.setdefault("plan_groups", {}).setdefault(plan, old["plan_groups"][plan])
    conn.execute(
        "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
        (json.dumps(new, sort_keys=True, separators=(",", ":")), str(new_id)),
    )
