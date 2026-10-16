"""Member plan selection facts reused during Shipping QA presentation."""

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_presentation_reads import (
    presentation_active,
    presentation_read,
)


def read_plan_rows(conn, plan_ids, *, lock_plan):
    """Read each definition once, optionally holding plans in stable ID order.

    Case writers update the owning plan before replacing its cases. Admission
    holds those plan locks until its transaction ends; presentation never locks.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.deployment_requirement_snapshot_format import (
        PLAN_FIELDS,
        PLAN_CASE_COLUMNS,
    )

    ids = tuple(sorted(set(int(value) for value in plan_ids)))
    if not ids:
        return {}
    postgres = db_backend.connection_is_postgres(conn)
    markers = ",".join("%s" if postgres else "?" for _ in ids)
    lock = " FOR UPDATE" if lock_plan and postgres else ""
    plans = query_rows(
        conn,
        f"SELECT {','.join((*PLAN_FIELDS, 'retired_at'))} "
        f"FROM qa_plans WHERE id IN ({markers}) ORDER BY id{lock}",
        ids,
    )
    columns = ",".join("c." + field for field in PLAN_CASE_COLUMNS)
    cases = query_rows(
        conn,
        f"SELECT {columns},m.name AS method_name,m.runner_id,"
        "m.required_capability_kinds,m.verdict_path,m.config_contract_id "
        "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
        f"WHERE c.plan_id IN ({markers}) ORDER BY c.position,c.id",
        ids,
    )
    rows = {int(plan["id"]): (plan, []) for plan in plans}
    for case in cases:
        if int(case["plan_id"]) in rows:
            rows[int(case["plan_id"])][1].append(case)
    return rows


def presented_plan_rows(conn, plan_id):
    from yoke_core.domain.deployment_qa_presentation_facts import presented_plan_ids

    ids = presented_plan_ids(conn)
    if ids is None or int(plan_id) not in ids:
        return None
    return presentation_read(
        conn,
        ("qa_presented_plans", ids),
        lambda: read_plan_rows(conn, ids, lock_plan=False),
    ).get(int(plan_id))


def plan_snapshot_row(conn, plan_id, *, lock_plan):
    from yoke_core.domain.deployment_requirement_snapshot_format import PLAN_FIELDS
    from yoke_core.domain import db_backend
    from yoke_core.domain.deployment_requirement_snapshots import _p

    batch = presented_plan_rows(conn, plan_id) if not lock_plan else None
    if batch is not None:
        return dict(batch[0])
    lock = (
        " FOR UPDATE" if lock_plan and db_backend.connection_is_postgres(conn) else ""
    )
    rows = query_rows(
        conn,
        f"SELECT {','.join((*PLAN_FIELDS, 'retired_at'))} "
        f"FROM qa_plans WHERE id={_p(conn)}{lock}",
        (int(plan_id),),
    )
    return rows[0] if rows else None


def plan_snapshot_cases(conn, plan_id, *, lock_plan):
    from yoke_core.domain.deployment_requirement_snapshot_format import (
        PLAN_CASE_COLUMNS,
    )
    from yoke_core.domain.deployment_requirement_snapshots import _p

    batch = presented_plan_rows(conn, plan_id) if not lock_plan else None
    if batch is not None:
        return [dict(row) for row in batch[1]]
    columns = ",".join("c." + field for field in PLAN_CASE_COLUMNS)
    return query_rows(
        conn,
        f"SELECT {columns},m.name AS method_name,m.runner_id,"
        "m.required_capability_kinds,m.verdict_path,m.config_contract_id "
        "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
        f"WHERE c.plan_id={_p(conn)} ORDER BY c.position,c.id",
        (int(plan_id),),
    )


def _member_attached_plan_ids(conn, member, snapshot, target, environment_id):
    return presentation_read(
        conn,
        (
            "qa_attached_plans",
            member,
            json.dumps(snapshot, sort_keys=True),
            environment_id,
            str((target.get("environment") or {}).get("name") or ""),
        ),
        lambda: _read_member_attached_plan_ids(
            conn, member, snapshot, target, environment_id
        ),
    )


def _read_member_attached_plan_ids(
    conn: Any,
    member: int,
    snapshot: Mapping | None,
    target: Mapping,
    environment_id: int | None,
) -> set[int]:
    """Plans one member selects for this stage: attached, frozen or admitted."""
    from yoke_core.domain.deployment_qa_frozen_plan_selection import member_requirements
    from yoke_core.domain.qa_deployment_member_attached_plans import (
        attached_member_plan_ids,
    )

    ids = set(
        attached_member_plan_ids(
            conn, member_item_id=member, environment_id=environment_id
        )
    )
    for value in (snapshot or {}).get("plans") or []:
        if value.get("selected_by_agent"):
            continue
        if (value.get("attachment") or {}).get("qa_phase") == "post_deploy":
            ids.add(int(value["plan"]["id"]))
    admitted = {"member_item_id": member, "member_snapshot": snapshot}
    for requirement in member_requirements(conn, admitted, target=target):
        if requirement.get("plan_id") is not None:
            ids.add(int(requirement["plan_id"]))
    return ids


def _other_members_plan_ids(
    conn: Any, run_id: str, member: int, target: Mapping, environment_id: int | None
) -> set[int]:
    """Plans any other member of the run attached for the same environment."""

    def read():
        from yoke_core.domain.deployment_qa_presentation_facts import run_member_rows

        batch = presentation_active()
        member_filter = "" if batch else " AND item_id<>%s"
        rows = run_member_rows(conn, run_id)
        if rows is not None:
            rows = list(rows.values())
        else:
            rows = query_rows(
                conn,
                "SELECT item_id,requirement_snapshot FROM deployment_run_items "
                f"WHERE run_id=%s{member_filter} ORDER BY item_id",
                (run_id,) if batch else (run_id, member),
            )
        return {
            int(row["item_id"]): _member_attached_plan_ids(
                conn,
                int(row["item_id"]),
                row["requirement_snapshot"]
                if isinstance(row["requirement_snapshot"], Mapping)
                else json.loads(str(row["requirement_snapshot"] or "{}")),
                target,
                environment_id,
            )
            for row in rows
        }

    plans = presentation_read(
        conn,
        (
            "qa_member_plans",
            run_id,
            environment_id,
            str((target.get("environment") or {}).get("name") or ""),
        ),
        read,
    )
    return set().union(*(ids for other, ids in plans.items() if other != member))


def _formed_group_plan_ids(conn: Any, run_id: str, stage_name: str) -> set[int]:
    return presentation_read(
        conn,
        ("qa_formed_groups", run_id, stage_name),
        lambda: _read_formed_group_plan_ids(conn, run_id, stage_name),
    )


def _read_formed_group_plan_ids(conn: Any, run_id: str, stage_name: str) -> set[int]:
    """Plans whose shared group already holds live memberless rows in this stage."""
    from yoke_core.domain.qa_obligation_settlement import unretracted_requirement_sql
    from yoke_core.domain.deployment_qa_presentation_facts import stage_requirement_rows

    rows = stage_requirement_rows(conn, run_id, stage_name)
    if rows is not None:
        return {
            int(row["plan_id"])
            for row in rows
            if row["plan_id"] is not None
            and row["deployment_member_item_id"] is None
            and row["unretracted"]
        }

    return {
        int(row["plan_id"])
        for row in query_rows(
            conn,
            "SELECT DISTINCT plan_id FROM qa_requirements "
            "WHERE deployment_run_id=%s AND deployment_stage=%s "
            "AND deployment_member_item_id IS NULL AND plan_id IS NOT NULL "
            f"AND {unretracted_requirement_sql(conn)}",
            (run_id, stage_name),
        )
    }
