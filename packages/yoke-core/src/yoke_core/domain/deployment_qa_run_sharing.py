"""The QA a release's members share, and what removing a member cancelled.

Every QA presentation draws a shared plan once, under Run QA, labelled with
the members whose frozen selection attaches it; a member's own section only
points at it. A removed member is drawn as removed with the count of checks
its removal cancelled, never as open QA. This read is the single source of
both facts for the run page, Shipping and the Inbox.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES


def _markers(values) -> str:
    return ",".join("%s" for _ in values)


def _snapshot_plan_ids(raw: Any) -> set[int]:
    from yoke_core.domain.deployment_member_qa_sources import decoded

    try:
        snapshot = decoded(raw, {})
    except ValueError:
        # The canonical subject reader reports a malformed snapshot.
        return set()
    if not isinstance(snapshot, dict):
        return set()
    ids = set()
    for entry in snapshot.get("plans") or []:
        plan = entry.get("plan") if isinstance(entry, dict) else None
        if isinstance(plan, dict) and plan.get("id") is not None:
            ids.add(int(plan["id"]))
    # A plan reaches a member through an admitted plan requirement as well.
    for requirement in snapshot.get("requirements") or []:
        if isinstance(requirement, dict) and requirement.get("plan_id") is not None:
            ids.add(int(requirement["plan_id"]))
    return ids


def _live_attachments(conn: Any, item_ids: set[int]) -> dict[int, set[int]]:
    from yoke_core.domain.qa_plan_attachment_reads import live_item_attachment_sql

    if not item_ids:
        return {}
    from yoke_core.domain.deployment_qa_presentation_facts import (
        attachment_rows,
        presented_member_ids,
    )

    members = presented_member_ids(conn)
    if members is not None and item_ids <= set(members):
        return {
            item: {
                int(row["plan_id"])
                for row in attachment_rows(conn, item)
                if row["live"]
            }
            for item in item_ids
        }
    items = tuple(sorted(item_ids))
    attached: dict[int, set[int]] = defaultdict(set)
    for row in query_rows(
        conn,
        "SELECT a.item_id,a.plan_id FROM qa_plan_item_attachments a "
        f"WHERE a.item_id IN ({_markers(items)}) AND a.qa_phase='post_deploy' "
        f"AND {live_item_attachment_sql(conn, 'a')}",
        items,
    ):
        attached[int(row["item_id"])].add(int(row["plan_id"]))
    return attached


def _shared_plan_counts(conn: Any, run_ids: tuple[str, ...]) -> dict:
    """Shared plans per run with their live check count.

    An unretracted copy keeps its plan shared; only checks neither retracted
    nor superseded are counted, so a corrected case counts once.
    """
    from yoke_core.domain.deployment_qa_shared_plans import shared_target_identity
    from yoke_core.domain.qa_obligation_settlement import unretracted_requirement_sql

    rows = query_rows(
        conn,
        "SELECT q.deployment_run_id,q.plan_id,q.execution_target_json,"
        "q.superseded_by_requirement_id,p.slug,p.name "
        "FROM qa_requirements q JOIN qa_plans p ON p.id=q.plan_id "
        f"WHERE q.deployment_run_id IN ({_markers(run_ids)}) "
        "AND q.deployment_member_item_id IS NULL AND q.qa_phase='post_deploy' "
        f"AND {unretracted_requirement_sql(conn, 'q')}",
        run_ids,
    )
    counts: dict = defaultdict(dict)
    for row in rows:
        if not shared_target_identity(row["execution_target_json"]):
            continue
        plan_id = int(row["plan_id"])
        entry = counts[str(row["deployment_run_id"])].setdefault(
            plan_id,
            {
                "plan_id": plan_id,
                "plan": row["slug"],
                "plan_name": row["name"] or row["slug"],
                "case_count": 0,
            },
        )
        if row["superseded_by_requirement_id"] is None:
            entry["case_count"] += 1
    return counts


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
    """Reuse the presentation's frozen rows and status; scalar reads keep their set."""
    from yoke_core.domain.deployment_qa_presentation_facts import run_member_rows

    batches = [run_member_rows(conn, run) for run in runs]
    if all(batch is not None for batch in batches):
        return sorted(
            (row for batch in batches for row in batch.values()),
            key=lambda row: int(row["item_id"]),
        )
    return query_rows(
        conn,
        "SELECT dri.run_id,dri.item_id,dri.requirement_snapshot,dr.status "
        "FROM deployment_run_items dri JOIN deployment_runs dr ON dr.id=dri.run_id "
        f"WHERE dri.run_id IN ({_markers(runs)}) ORDER BY dri.item_id",
        runs,
    )


def run_qa_sharing(conn: Any, run_ids: Iterable[str]) -> dict[str, dict]:
    """Per run: ``shared_plans`` with their sharing members, ``removed_members``."""
    runs = tuple(sorted({str(run) for run in run_ids if run}))
    if not runs:
        return {}
    counts = _shared_plan_counts(conn, runs)
    sharing: dict = defaultdict(lambda: defaultdict(list))
    if counts:
        live = tuple(sorted(counts))
        members = _sharing_members(conn, live)
        attached = _live_attachments(
            conn,
            {
                int(row["item_id"])
                for row in members
                if str(row["status"]) not in TERMINAL_RUN_STATUSES
            },
        )
        for row in members:
            run_id, item = str(row["run_id"]), int(row["item_id"])
            plans = _snapshot_plan_ids(row["requirement_snapshot"])
            # An active release answers the member's current attachments,
            # as its Item QA does; a finished one keeps its frozen selection.
            if str(row["status"]) not in TERMINAL_RUN_STATUSES:
                plans |= attached.get(item, set())
            for plan_id in sorted(plans):
                if plan_id in counts[run_id]:
                    sharing[run_id][plan_id].append(item)
    removed = removed_members(conn, runs)
    return {
        run: {
            "shared_plans": [
                {**plan, "sharing_item_ids": sharing[run][plan_id]}
                for plan_id, plan in sorted(counts.get(run, {}).items())
            ],
            "removed_members": removed.get(run, []),
        }
        for run in runs
    }


def member_shared_plan_ids(sharing: dict, run_id: str, member: int) -> set[int]:
    """Plans a member shares on one run; their checks never enter its section."""
    return {
        int(plan["plan_id"])
        for plan in (sharing.get(str(run_id)) or {}).get("shared_plans", [])
        if int(member) in plan["sharing_item_ids"]
    }


__all__ = [
    "cancelled_check_counts",
    "member_shared_plan_ids",
    "removed_members",
    "run_qa_sharing",
]
