"""Pin item-owned versus driver-owned post-deploy plans at item QA entry."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows

OWNERS = "item_qa_plan_owners"


def _snapshot(conn: Any, run_id: str) -> dict:
    from yoke_core.domain.deployment_qa_presentation_facts import run_facts

    facts = run_facts(conn, str(run_id))
    if facts is not None:
        raw = facts.get("requirement_snapshot")
    else:
        row = conn.execute(
            "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s",
            (str(run_id),),
        ).fetchone()
        raw = row[0] if row is not None else None
    return dict(raw) if isinstance(raw, Mapping) else json.loads(raw or "{}")


def plan_owners(conn: Any, run_id: str) -> dict[int, int | None]:
    """An item id owns a single-member plan; None assigns it to the driver.

    Before entry, previews classify the live attachments without writing.
    Plans first attached after entry are classified once on the next dispatch.
    Existing plan ownership never changes with later attachments or removals.
    A sole attacher a closed group in the run's lineage already answered keeps
    that group's credit, so the plan stays with the driver and owes it nothing.
    """
    from yoke_core.domain.deployment_qa_plan_group_coverage import lineage_coverage
    from yoke_core.domain.deployment_qa_plan_groups import attached_plans, run_groups
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    def read():
        from yoke_core.domain.deployment_qa_presentation_facts import presented_run_ids

        runs = presented_run_ids(conn, str(run_id))
        groups = (
            presentation_read(
                conn, ("plan_groups", runs), lambda: run_groups(conn, runs)
            )
            if runs
            else run_groups(conn, run_id)
        )
        return classify_owners(
            _snapshot(conn, run_id),
            {group.plan_id for group in groups if group.run_id == str(run_id)},
            attached_plans(conn, run_id),
            lineage_coverage(conn, run_id),
        )

    return presentation_read(conn, ("item_qa_plan_owners", str(run_id)), read)


def classify_owners(
    snapshot: Mapping, grouped_plans: set[int], attached: Mapping, covered: Mapping
) -> dict:
    """Apply pinned ownership first, then classify newly observed plans.

    ``covered`` maps each plan to the members its closed lineage groups answered.
    """
    owners = {int(plan): owner for plan, owner in snapshot.get(OWNERS, {}).items()}
    for plan in grouped_plans:
        owners.setdefault(plan, None)
    for plan, members in attached.items():
        sole = len(members) == 1 and members[0] not in covered.get(plan, ())
        owners.setdefault(plan, members[0] if sole else None)
    return owners


def retire_member_copies(conn: Any, run_id: str) -> list[int]:
    """Retract members' never-run own rows of plans a plan group answers.

    A member that was a plan's sole attacher got its own rows; once the plan
    becomes a group (a second member joined through takeover), those rows
    would stay owed beside the group and hold the run's settlement. Rows
    with any recorded run or result stay as evidence. Repeating this after
    a retry restored the rows retires them again.
    """
    from yoke_core.domain.deployment_qa_plan_groups import lineage_run_ids, run_groups
    from yoke_core.domain.qa_plan_attachment_retract import retract_requirements

    groups: dict[int, str] = {}
    for group in run_groups(conn, lineage_run_ids(conn, run_id)):
        if not group.retracted:
            groups[group.plan_id] = group.group_id
    owners = plan_owners(conn, run_id)
    plans = sorted(p for p in groups if p in owners and owners[p] is None)
    if not plans:
        return []
    rows = query_rows(
        conn,
        "SELECT q.id,q.plan_id FROM qa_requirements q WHERE q.deployment_run_id=%s "
        "AND q.plan_id=ANY(%s) AND q.deployment_member_item_id IS NOT NULL "
        "AND q.retracted_at IS NULL AND NOT EXISTS (SELECT 1 FROM qa_runs r "
        "WHERE r.qa_requirement_id=q.id) AND NOT EXISTS (SELECT 1 FROM "
        "qa_plan_execution_results x WHERE x.requirement_id=q.id) ORDER BY q.id",
        (str(run_id), plans),
    )
    by_plan: dict[int, list[int]] = {}
    for row in rows:
        by_plan.setdefault(int(row["plan_id"]), []).append(int(row["id"]))
    for plan, ids in by_plan.items():
        retract_requirements(
            conn,
            ids,
            reason=f"replaced by plan group {groups[plan]}",
            source="deployment_run",
        )
    return [rid for ids in by_plan.values() for rid in ids]


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
        "SELECT DISTINCT q.deployment_stage FROM qa_requirements q "
        "JOIN deployment_runs r ON r.id=q.deployment_run_id WHERE r.id=%s "
        "AND r.composition_frozen_at IS NOT NULL AND q.deployment_member_item_id=%s "
        "AND q.plan_id=%s AND q.retracted_at IS NULL",
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
    """Members owing only driver-owned shared plans, with no holder-run cases."""
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
        if not own and owed[member] and not member_plan_ids(conn, run_id, member):
            found.add(member)
    return found


def open_walk_members(
    conn: Any, run_id: str, item_ids: Any, *, stage: str | None = None
) -> set[int]:
    """Members still walking on this run under an owner that has not ended."""
    return set(open_walk_owners(conn, run_id, item_ids, stage=stage))


def open_walk_owners(
    conn: Any, run_id: str, item_ids: Any, *, stage: str | None = None
) -> dict[int, list[str]]:
    """Each member still walking on this run, with the sessions walking it.

    A carried walk keeps going on its own execution, so its owner is never
    told to wait or rerun. An owner with recorded session end is excluded:
    its walk is the sweep's to settle, and the member is woken as usual.
    Upkeep, the driver and the fleet report all read this one rule; a
    presentation reads every presented run's open walks once.
    """
    from yoke_core.domain.deployment_qa_presentation_facts import presented_run_ids
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    members = {int(item) for item in item_ids}
    runs = presented_run_ids(conn, str(run_id))
    rows = (
        presentation_read(
            conn, ("qa_open_walks", runs), lambda: _open_walk_rows(conn, runs)
        )
        if runs
        else _open_walk_rows(conn, (str(run_id),), members)
    )
    owners: dict[int, list[str]] = {}
    for row in rows:
        member = int(row["item_id"])
        if (
            str(row["run_id"]) == str(run_id)
            and member in members
            and (stage is None or str(row["stage"]) == str(stage))
            and str(row["session_id"]) not in owners.get(member, [])
        ):
            owners.setdefault(member, []).append(str(row["session_id"]))
    return owners


def _open_walk_rows(conn: Any, runs: Any, members: Any = None) -> list:
    from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL

    member_filter = "" if members is None else "AND e.deployment_member_item_id=ANY(%s) "
    return query_rows(
        conn,
        "SELECT e.deployment_run_id AS run_id, e.deployment_stage AS stage, "
        "e.deployment_member_item_id AS item_id, e.session_id "
        "FROM qa_plan_executions e WHERE e.deployment_run_id=ANY(%s) "
        f"AND e.deployment_member_item_id IS NOT NULL {member_filter}"
        f"AND e.state IN ({LIVE_PLAN_EXECUTION_SQL}) AND NOT EXISTS ("
        "SELECT 1 FROM harness_sessions s WHERE s.session_id=e.session_id "
        "AND s.ended_at IS NOT NULL) ORDER BY e.session_id",
        (sorted(str(run) for run in runs),)
        + (() if members is None else (sorted(members),)),
    )


def transfer_plan_owners(
    conn: Any, old_id: str, new_id: str, *, requirement_ids: list[int]
) -> None:
    """Carry ownership and pinned cases only for plans whose moved rows ran;
    the successor pins every other plan from live state at item QA entry."""
    ran = conn.execute(
        "SELECT DISTINCT q.plan_id FROM qa_requirements q WHERE q.id=ANY(%s) "
        "AND q.plan_id IS NOT NULL AND (EXISTS (SELECT 1 FROM qa_runs r "
        "WHERE r.qa_requirement_id=q.id) OR EXISTS (SELECT 1 FROM "
        "qa_plan_execution_results x WHERE x.requirement_id=q.id))",
        (sorted(requirement_ids),),
    ).fetchall()
    old = _snapshot(conn, old_id)
    carried = {str(row[0]) for row in ran} & set(old.get(OWNERS, {}))
    if not carried:
        return
    new = _snapshot(conn, new_id)
    for plan in sorted(carried):
        owner = new.setdefault(OWNERS, {}).setdefault(plan, old[OWNERS][plan])
        pinned = (old.get("plan_groups") or {}).get(plan)
        if owner is not None and pinned is not None:
            new.setdefault("plan_groups", {}).setdefault(plan, pinned)
    conn.execute(
        "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
        (json.dumps(new, sort_keys=True, separators=(",", ":")), str(new_id)),
    )
