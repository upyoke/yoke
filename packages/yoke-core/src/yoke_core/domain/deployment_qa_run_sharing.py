"""A release's plan groups and what removing a member cancelled.

Every QA presentation draws a plan group once, under Run QA, labelled with
the items it answers; an item's own section only points at it. A plan group
is keyed by its ``group_id``, never by plan id: a run may hold a closed group
and an open group of one plan. An attached plan with no group yet shows as
``pending``; a closed group of an earlier run in the ``supersedes_run_id``
chain that answered a current member shows with that run's id. A removed
member is drawn as removed with the count of checks its removal cancelled,
never as open QA. This read is the single source of both facts for the run
page, Shipping and the Inbox.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_plan_groups import attached_plans, group_marker
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES


def _markers(values) -> str:
    return ",".join("%s" for _ in values)


def _lineages(conn: Any, runs: tuple[str, ...]) -> dict[str, list[str]]:
    """Each run's ``supersedes_run_id`` chain, oldest last, in one read."""
    lineages: dict[str, list[str]] = {run: [] for run in runs}
    for row in query_rows(
        conn,
        "WITH RECURSIVE chain(root,id,supersedes_run_id,depth) AS ("
        "SELECT id,id,supersedes_run_id,0 FROM deployment_runs WHERE id=ANY(%s) "
        "UNION ALL SELECT c.root,r.id,r.supersedes_run_id,c.depth+1 "
        "FROM deployment_runs r JOIN chain c ON r.id=c.supersedes_run_id "
        "WHERE c.depth<64) SELECT root,id FROM chain WHERE depth>0 ORDER BY root,depth",
        (list(runs),),
    ):
        lineages[str(row["root"])].append(str(row["id"]))
    return lineages


def _plan_groups(conn: Any, run_ids: list[str]) -> dict[str, dict]:
    """Every unretracted plan group of these runs, in one read, by ``group_id``.

    Only checks neither retracted nor superseded are counted, so a corrected
    case counts once.
    """
    groups: dict[str, dict] = {}
    retracted: set[str] = set()
    for row in query_rows(
        conn,
        "SELECT q.id,q.deployment_run_id,q.plan_id,q.execution_target_json,"
        "q.covered_item_ids,q.retracted_at,q.superseded_by_requirement_id,p.slug,p.name "
        "FROM qa_requirements q JOIN qa_plans p ON p.id=q.plan_id "
        "WHERE q.deployment_run_id=ANY(%s) AND q.deployment_member_item_id IS NULL "
        "AND q.plan_id IS NOT NULL ORDER BY q.id",
        (sorted(set(run_ids)),),
    ):
        marker = group_marker(row["execution_target_json"])
        if marker is None:
            continue
        group_id = str(marker["group_id"])
        if row["retracted_at"] is not None:
            # A retraction withdraws the whole group; a later attacher gets a new one.
            retracted.add(group_id)
        group = groups.setdefault(
            group_id,
            {
                "group_id": group_id,
                "plan_id": int(row["plan_id"]),
                "plan": row["slug"],
                "plan_name": row["name"] or row["slug"],
                "run_id": str(row["deployment_run_id"]),
                "case_count": 0,
                "covered_item_ids": None,
            },
        )
        covered = row["covered_item_ids"]
        if isinstance(covered, str):
            covered = json.loads(covered)
        if covered is not None:
            group["covered_item_ids"] = sorted(int(item) for item in covered)
        if row["retracted_at"] is None and row["superseded_by_requirement_id"] is None:
            group["case_count"] += 1
    return {key: value for key, value in groups.items() if key not in retracted}


def cancelled_check_counts(conn: Any, removed: dict[str, list[int]]) -> dict:
    """Checks each removed member's removal cancelled, by (run, item)."""
    runs = tuple(sorted(run for run, items in removed.items() if items))
    items = tuple(sorted({item for run in runs for item in removed[run]}))
    if not runs:
        return {}
    return {
        (str(row["deployment_run_id"]), int(row["item_id"])): int(row["cancelled"])
        for row in query_rows(
            conn,
            "SELECT deployment_run_id,deployment_member_item_id AS item_id,"
            "count(*) AS cancelled FROM qa_requirements "
            f"WHERE deployment_run_id IN ({_markers(runs)}) "
            f"AND deployment_member_item_id IN ({_markers(items)}) "
            "AND retracted_at IS NOT NULL "
            "GROUP BY deployment_run_id,deployment_member_item_id",
            (*runs, *items),
        )
    }


def removed_members(conn: Any, run_ids: tuple[str, ...]) -> dict:
    """Per run: each removed member and how many of its checks were cancelled."""
    from yoke_core.domain.deployment_run_membership_removals import (
        parse_membership_removals,
    )

    removed = {
        str(run["id"]): sorted(
            {
                int(entry["item_id"])
                for entry in parse_membership_removals(
                    run["membership_removals"], str(run["id"])
                )
            }
        )
        for run in query_rows(
            conn,
            "SELECT id,membership_removals FROM deployment_runs "
            f"WHERE id IN ({_markers(run_ids)})",
            run_ids,
        )
    }
    cancelled = cancelled_check_counts(conn, removed)
    return {
        run: [
            {"item_id": item, "cancelled_count": cancelled.get((run, item), 0)}
            for item in items
        ]
        for run, items in removed.items()
    }


def _sharing_members(conn, runs):
    """Reuse the presentation's member rows and status; scalar reads keep their set."""
    from yoke_core.domain.deployment_qa_presentation_facts import run_member_rows

    batches = [run_member_rows(conn, run) for run in runs]
    if all(batch is not None for batch in batches):
        return sorted(
            (row for batch in batches for row in batch.values()),
            key=lambda row: int(row["item_id"]),
        )
    return query_rows(
        conn,
        "SELECT dri.run_id,dri.item_id,dr.status "
        "FROM deployment_run_items dri JOIN deployment_runs dr ON dr.id=dri.run_id "
        f"WHERE dri.run_id IN ({_markers(runs)}) ORDER BY dri.item_id",
        runs,
    )


def _pending_plans(conn: Any, plan_ids: set[int]) -> dict[int, dict]:
    """Owed plans with no plan group yet, with their cases, in one read."""
    if not plan_ids:
        return {}
    plans: dict[int, dict] = {}
    for row in query_rows(
        conn,
        "SELECT p.id AS plan_id,p.slug,p.name,p.project_id,c.case_key,"
        "c.method_id,m.name AS method_name,c.instructions "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "LEFT JOIN qa_methods m ON m.id=c.method_id "
        "WHERE p.id=ANY(%s) ORDER BY p.id,c.position",
        (sorted(plan_ids),),
    ):
        plan = plans.setdefault(
            int(row["plan_id"]),
            {
                "plan_id": int(row["plan_id"]),
                "plan": row["slug"],
                "plan_name": row["name"] or row["slug"],
                "cases": [],
            },
        )
        plan["cases"].append(
            {
                "plan_id": plan["plan_id"],
                "plan": plan["plan"],
                "project_id": row["project_id"],
                "case_key": row["case_key"],
                "method_id": row["method_id"],
                "method_name": row["method_name"],
                "instructions": row["instructions"],
                "qa_phase": "post_deploy",
                "pending_obligation": True,
            }
        )
    return plans


def _run_entries(
    run: str,
    groups: dict[str, dict],
    earlier: list[str],
    members: set[int],
    attached: dict[int, list[int]] | None,
) -> tuple[list[dict], dict[int, list[int]]]:
    """One run's plan groups, earlier-run closed groups it answers, and owed plans.

    ``attached`` is None for a finished run: it keeps the groups it held.
    """
    entries: list[dict] = []
    covered: dict[int, set[int]] = defaultdict(set)
    open_plans: set[int] = set()
    for group in groups.values():
        closed = group["covered_item_ids"] is not None
        if group["run_id"] == run:
            if closed:
                sharing = group["covered_item_ids"]
                covered[group["plan_id"]].update(sharing)
            else:
                open_plans.add(group["plan_id"])
                sharing = (attached or {}).get(group["plan_id"], [])
            entries.append(
                {**group, "closed": closed, "earlier_run_id": None,
                 "sharing_item_ids": list(sharing)}
            )
        elif group["run_id"] in earlier and closed:
            answered = members.intersection(group["covered_item_ids"])
            if not answered:
                continue
            covered[group["plan_id"]].update(answered)
            entries.append(
                {**group, "closed": True, "earlier_run_id": group["run_id"],
                 "sharing_item_ids": list(group["covered_item_ids"])}
            )
    owed = {
        plan_id: [item for item in items if item not in covered[plan_id]]
        for plan_id, items in (attached or {}).items()
        if plan_id not in open_plans
    }
    return entries, {plan_id: items for plan_id, items in owed.items() if items}


def run_qa_sharing(conn: Any, run_ids: Iterable[str]) -> dict[str, dict]:
    """Per run: ``plan_groups`` with the items each answers, ``removed_members``.

    An active run whose members attach a plan before its group exists shows
    the plan ``pending`` with its cases, so every surface draws it once
    before item-qa creates the group. Group rows are read once for every run
    on the page and the runs they superseded.
    """
    runs = tuple(sorted({str(run) for run in run_ids if run}))
    if not runs:
        return {}
    members = _sharing_members(conn, runs)
    by_run: dict[str, set[int]] = defaultdict(set)
    active = set()
    for row in members:
        by_run[str(row["run_id"])].add(int(row["item_id"]))
        if str(row["status"]) not in TERMINAL_RUN_STATUSES:
            active.add(str(row["run_id"]))
    lineages = _lineages(conn, runs)
    groups = _plan_groups(
        conn, [*runs, *(run for chain in lineages.values() for run in chain)]
    )
    entries: dict[str, list[dict]] = {}
    owed: dict[str, dict[int, list[int]]] = {}
    for run in runs:
        entries[run], owed[run] = _run_entries(
            run, groups, lineages[run], by_run[run],
            attached_plans(conn, run) if run in active else None,
        )
    pending = _pending_plans(conn, {plan for plans in owed.values() for plan in plans})
    for run, plans in owed.items():
        for plan_id, items in sorted(plans.items()):
            plan = pending.get(plan_id)
            if plan is None:
                continue
            entries[run].append(
                {**plan, "group_id": None, "run_id": None, "case_count": len(plan["cases"]),
                 "covered_item_ids": None, "closed": False, "earlier_run_id": None,
                 "pending": True, "sharing_item_ids": items}
            )
    removed = removed_members(conn, runs)
    return {
        run: {
            "plan_groups": sorted(
                entries[run],
                # Stable: a plan's groups keep creation order after earlier runs'.
                key=lambda entry: (entry["plan_id"], entry["earlier_run_id"] is None,
                                   entry.get("pending", False)),
            ),
            "removed_members": removed.get(run, []),
        }
        for run in runs
    }


__all__ = [
    "cancelled_check_counts",
    "removed_members",
    "run_qa_sharing",
]
