"""Page-wide durable decision, dependency, deployment and CI action facts."""

from __future__ import annotations

import json
from typing import Any, Iterable

from yoke_core.domain.audiences import member_matches_for_audiences
from yoke_core.domain.actor_render import render_actor_names
from yoke_core.domain.next_actor import action
from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.schema_common import _table_exists


def _rows(conn, sql, params):
    cursor = conn.execute(sql, tuple(params))
    columns = [col[0] for col in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def _context(raw):
    return raw if isinstance(raw, dict) else json.loads(raw or "{}")


def next_actor_facts(
    conn: Any, *, session_ids: Iterable[str] = (), item_ids: Iterable[int] = ()
) -> tuple[dict, dict]:
    """Read each fact kind once for the page, never once per rendered row.

    The maps are keyed by session id and integer item id. A decision's
    audience resolves through shared human-role membership, including org
    inheritance; absent membership names the repair owner instead of a
    fictitious operator. Schema absence on an older serving tree is no fact.
    """
    sessions = tuple(dict.fromkeys(session_ids))
    items = tuple(dict.fromkeys(int(value) for value in item_ids))
    from yoke_core.domain.work_claim_targets import scope_int_sql

    held = {}
    if sessions and _table_exists(conn, "work_claims"):
        p = placeholder(conn)
        scope = scope_int_sql(conn, "scope", "item_id")
        for row in _rows(
            conn,
            f"SELECT session_id,{scope} AS item_id FROM work_claims "
            "WHERE target_kind='item' AND released_at IS NULL "
            f"AND session_id IN ({','.join(p for _ in sessions)}) ORDER BY id",
            sessions,
        ):
            if row["item_id"] is not None:
                held.setdefault(row["session_id"], []).append(int(row["item_id"]))
        items = tuple(
            dict.fromkeys((*items, *(iid for ids in held.values() for iid in ids)))
        )
    by_session: dict[str, dict] = {sid: {} for sid in sessions}
    by_item: dict[int, dict] = {iid: {} for iid in items}
    if not sessions and not items:
        return by_session, by_item
    run_decisions = {}
    p = placeholder(conn)

    def slots(values):
        return ",".join(p for _ in values)

    if _table_exists(conn, "decision_requests"):
        # Subject ids are parsed after this scoped read; no casts of opaque
        # subject keys, and no dependency on telemetry or receipt events.
        arms, params = [], []
        if sessions:
            arms.append(f"requesting_session_id IN ({slots(sessions)})")
            params.extend(sessions)
        if items:
            arms.append(
                f"project_id IN (SELECT project_id FROM items WHERE id IN ({slots(items)}))"
            )
            params.extend(items)
        decisions = _rows(
            conn,
            "SELECT id,kind,subject_type,subject_key,subject_context,"
            "requesting_session_id,audience_id,created_at FROM decision_requests "
            "WHERE status='pending' AND (" + " OR ".join(arms) + ") "
            "ORDER BY created_at,id",
            params,
        )
        qa_subjects = [
            int(row["subject_key"])
            for row in decisions
            if row["subject_type"] == "qa_requirement"
            and str(row["subject_key"]).isdecimal()
        ]
        qa_items = {}
        if qa_subjects and _table_exists(conn, "qa_requirements"):
            qa_items = {
                str(row["id"]): row["item_id"]
                for row in _rows(
                    conn,
                    "SELECT id,COALESCE(item_id,epic_id,deployment_member_item_id) AS item_id "
                    f"FROM qa_requirements WHERE id IN ({slots(qa_subjects)})",
                    qa_subjects,
                )
            }
        memberships = member_matches_for_audiences(
            conn, {row["audience_id"] for row in decisions if row["audience_id"]}
        )
        names = render_actor_names(
            conn,
            {member["actor_id"] for group in memberships.values() for member in group},
        )
        for row in decisions:
            context = _context(row["subject_context"])
            iid = context.get("item_id") or qa_items.get(str(row["subject_key"]))
            if iid is None and row["subject_type"] in {
                "item_transition",
                "item_merge_candidate",
            }:
                head = str(row["subject_key"]).split(":", 1)[0]
                iid = int(head) if head.isdecimal() else None
            people = sorted(
                {
                    member["actor_id"]
                    for member in memberships.get(row["audience_id"], [])
                }
            )
            projected = action(
                "operator" if people else "parent_or_steering",
                context.get("question") or context.get("reason") or row["kind"],
                row["created_at"],
                request_id=row["id"],
                people=[{"actor_id": aid, "name": names.get(aid)} for aid in people],
                recovery=None
                if people
                else "Repair the decision audience to reach an active person.",
            )
            if row["subject_type"] == "deployment_stage":
                run_decisions.setdefault(
                    str(row["subject_key"]).rsplit(":", 1)[0], projected
                )
            if row["requesting_session_id"] in by_session:
                by_session[row["requesting_session_id"]].setdefault(
                    "pending_decision", projected
                )
            if iid is not None and int(iid) in by_item:
                by_item[int(iid)].setdefault("pending_decision", projected)
    if sessions and _table_exists(conn, "session_ci_run_waits"):
        for row in _rows(
            conn,
            "SELECT session_id,run_id,created_at FROM session_ci_run_waits "
            f"WHERE session_id IN ({slots(sessions)}) AND conclusion='' "
            "AND notified_at IS NULL ORDER BY created_at,id",
            sessions,
        ):
            by_session[row["session_id"]].setdefault(
                "ci_wait",
                action(
                    "ci_or_deploy",
                    "ci_run_in_progress",
                    row["created_at"],
                    run_id=row["run_id"],
                ),
            )
    if items and all(
        _table_exists(conn, name)
        for name in ("deployment_runs", "deployment_run_items")
    ):
        for row in _rows(
            conn,
            "SELECT m.item_id,r.id,r.created_at,r.started_at,r.current_stage "
            "FROM deployment_run_items m JOIN deployment_runs r ON r.id=m.run_id "
            f"WHERE m.item_id IN ({slots(items)}) AND r.status IN ('created','executing') "
            "ORDER BY r.created_at,r.id",
            items,
        ):
            if row["id"] in run_decisions:
                by_item[int(row["item_id"])].setdefault(
                    "pending_decision", run_decisions[row["id"]]
                )
            by_item[int(row["item_id"])].setdefault(
                "deployment_wait",
                action(
                    "ci_or_deploy",
                    "release_run_in_progress",
                    row["started_at"] or row["created_at"],
                    run_id=row["id"],
                    stage=row["current_stage"],
                ),
            )
    from yoke_core.domain.session_control_health_facts import gating_blockers

    for iid, blocker in gating_blockers(conn, items).items():
        by_item[iid]["dependency_wait"] = action(
            "another_item",
            "dependency_unsatisfied",
            blocker.get("since"),
            blocking_item=blocker["blocking_item"],
            gate_point=blocker["gate_point"],
        )
    for sid, ids in held.items():
        for iid in ids:
            for key, value in by_item[iid].items():
                by_session[sid].setdefault(key, value)
    return by_session, by_item
