"""Item-qa plan groups: each attached post-deploy plan runs once per release.

A plan group is the memberless rows of one plan at an item-scoped stage. Its
target carries ``deployment.shared_plan = {plan_id, source_revision,
group_id}``; ``group_id`` is set once at creation, so each group has its own
target digest and a run may hold closed groups and one open group of a plan.
A group stays open until the existing settlement rules accept it, then
records the run members attaching the plan in ``covered_item_ids``. That list
is written once and never changes; it is the only record of who a pass
credited.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yoke_core.domain.db_helpers import query_rows

#: Run snapshot key holding each plan pinned at its first group in the run.
PINNED_PLANS = "plan_groups"


@dataclass(frozen=True)
class PlanGroup:
    group_id: str
    plan_id: int
    stage: str
    run_id: str
    digest: str
    target: dict
    requirement_ids: tuple[int, ...]
    covered_item_ids: tuple[int, ...] | None
    retracted: bool

    @property
    def closed(self) -> bool:
        return self.covered_item_ids is not None

    @property
    def open(self) -> bool:
        return not self.closed and not self.retracted


def _json(raw: Any) -> Any:
    if raw is None or isinstance(raw, (Mapping, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return None


def group_marker(raw_target: Any) -> Mapping | None:
    """The ``shared_plan`` marker of a plan-group target, else None."""
    target = _json(raw_target)
    if not isinstance(target, Mapping):
        return None
    marker = (target.get("deployment") or {}).get("shared_plan")
    return marker if isinstance(marker, Mapping) and marker.get("group_id") else None


def run_groups(
    conn: Any, run_ids: Any, stage: str | None = None, *, plan_id: int | None = None
) -> list[PlanGroup]:
    """Every plan group held by these runs, one read, ordered by creation."""
    ids = sorted({str(run) for run in ([run_ids] if isinstance(run_ids, str) else run_ids)})
    if not ids:
        return []
    filters, params = "", [ids]
    if stage is not None:
        filters += " AND deployment_stage=%s"
        params.append(str(stage))
    if plan_id is not None:
        filters += " AND plan_id=%s"
        params.append(int(plan_id))
    rows = query_rows(
        conn,
        "SELECT id,deployment_run_id,deployment_stage,plan_id,execution_target_json,"
        "execution_target_digest,covered_item_ids,retracted_at FROM qa_requirements "
        "WHERE deployment_run_id=ANY(%s) AND deployment_member_item_id IS NULL "
        f"AND plan_id IS NOT NULL{filters} ORDER BY id",
        tuple(params),
    )
    found: dict[str, dict] = {}
    for row in rows:
        marker = group_marker(row["execution_target_json"])
        if marker is None:
            continue
        group = found.setdefault(
            str(marker["group_id"]),
            {
                "group_id": str(marker["group_id"]),
                "plan_id": int(row["plan_id"]),
                "stage": str(row["deployment_stage"]),
                "run_id": str(row["deployment_run_id"]),
                "digest": str(row["execution_target_digest"]),
                "target": dict(_json(row["execution_target_json"])),
                "ids": [],
                "covered": None,
                "retracted": False,
            },
        )
        group["ids"].append(int(row["id"]))
        covered = _json(row["covered_item_ids"])
        if covered is not None:
            group["covered"] = tuple(sorted(int(value) for value in covered))
        # Retraction withdraws a whole group; its passed rows stay as evidence.
        group["retracted"] = group["retracted"] or row["retracted_at"] is not None
    return [
        PlanGroup(
            group_id=value["group_id"],
            plan_id=value["plan_id"],
            stage=value["stage"],
            run_id=value["run_id"],
            digest=value["digest"],
            target=value["target"],
            requirement_ids=tuple(value["ids"]),
            covered_item_ids=value["covered"],
            retracted=value["retracted"],
        )
        for value in found.values()
    ]


def open_group(conn: Any, run_id: str, stage: str, plan_id: int) -> PlanGroup | None:
    """The run's one open group of this plan at this stage, if any."""
    return next(
        (g for g in run_groups(conn, run_id, stage, plan_id=plan_id) if g.open), None
    )


def group_for_target(conn: Any, run_id: str, target: Mapping) -> PlanGroup | None:
    marker = group_marker(target)
    if marker is None:
        return None
    return next(
        (
            group
            for group in run_groups(conn, run_id, plan_id=int(marker["plan_id"]))
            if group.group_id == str(marker["group_id"])
        ),
        None,
    )


def attached_plans(conn: Any, run_id: str) -> dict[int, list[int]]:
    """Each owed post-deploy plan of the run's current members, with its attachers."""
    rows = query_rows(
        conn,
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
        (run_id,),
    )
    from yoke_core.domain.deployment_qa_member_plans import members_plan_ids

    owed = members_plan_ids(conn, (int(row["item_id"]) for row in rows), run_id)
    plans: dict[int, list[int]] = {}
    for member in sorted(owed):
        for plan_id in sorted(owed[member]):
            plans.setdefault(plan_id, []).append(member)
    return plans


def attaching_members(conn: Any, run_id: str, plan_id: int) -> list[int]:
    return attached_plans(conn, run_id).get(int(plan_id), [])


def lineage_run_ids(conn: Any, run_id: str) -> list[str]:
    """This run and the runs it superseded, newest first."""
    rows = query_rows(
        conn,
        "WITH RECURSIVE chain(id,supersedes_run_id,depth) AS ("
        "SELECT id,supersedes_run_id,0 FROM deployment_runs WHERE id=%s "
        "UNION ALL SELECT r.id,r.supersedes_run_id,c.depth+1 FROM deployment_runs r "
        "JOIN chain c ON r.id=c.supersedes_run_id WHERE c.depth<64) "
        "SELECT id FROM chain ORDER BY depth",
        (str(run_id),),
    )
    return [str(row["id"]) for row in rows]


def covered_members(conn: Any, run_id: str, plan_id: int) -> set[int]:
    """Members a closed group of this plan answered in this run or its predecessors."""
    return {
        member
        for group in run_groups(conn, lineage_run_ids(conn, run_id), plan_id=plan_id)
        if group.closed
        for member in group.covered_item_ids or ()
    }


def unattached_open_groups(conn: Any, run_id: str) -> list[PlanGroup]:
    """Open groups no current member attaches any more."""
    plans = attached_plans(conn, run_id)
    return [g for g in run_groups(conn, run_id) if g.open and not plans.get(g.plan_id)]


def retract_unattached_groups(conn: Any, run_id: str, *, reason: str, source: str) -> list[int]:
    """Retract each open group left with no attacher; never a passed row.

    A retracted group is never reused: a later attacher gets a new group.
    """
    from yoke_core.domain.qa_latest_execution import latest_execution_id_sql
    from yoke_core.domain.qa_plan_attachment_retract import retract_requirements

    ids = [rid for group in unattached_open_groups(conn, run_id) for rid in group.requirement_ids]
    if not ids:
        return []
    rows = query_rows(
        conn,
        "SELECT r.id FROM qa_requirements r WHERE r.id=ANY(%s) AND r.retracted_at IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM qa_runs qr "
        f"WHERE qr.id=({latest_execution_id_sql('r.id')}) AND qr.verdict='pass')",
        (ids,),
    )
    retired = [int(row["id"]) for row in rows]
    retract_requirements(conn, retired, reason=reason, source=source)
    return retired


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
        snapshot = _json(row["requirement_snapshot"]) or {}
        own = [
            r for r in snapshot.get("requirements") or ()
            if isinstance(r, Mapping) and r.get("plan_id") is None
            and r.get("qa_phase") == "post_deploy"
        ]
        if not own and owed[member]:
            found.add(member)
    return found


def close_group(conn: Any, subject: Mapping) -> None:
    """Record who a passing group answered, once, under the caller's run lock."""
    marker = subject.get("shared_plan") or {}
    if not marker.get("group_id"):
        return
    from yoke_core.domain.qa_execution_environment_target import target_digest

    members = attaching_members(conn, str(subject["id"]), int(marker["plan_id"]))
    conn.execute(
        "UPDATE qa_requirements SET covered_item_ids=%s WHERE deployment_run_id=%s "
        "AND deployment_member_item_id IS NULL AND execution_target_digest=%s "
        "AND covered_item_ids IS NULL",
        (
            json.dumps(sorted(members)),
            str(subject["id"]),
            target_digest(subject["shared_target"]),
        ),
    )


__all__ = [
    "PINNED_PLANS",
    "PlanGroup",
    "attached_plans",
    "attaching_members",
    "close_group",
    "covered_members",
    "group_for_target",
    "group_marker",
    "lineage_run_ids",
    "open_group",
    "plan_only_members",
    "retract_unattached_groups",
    "run_groups",
    "unattached_open_groups",
]
