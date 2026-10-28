"""Plan definitions read once per presentation, for snapshots and plan groups."""


from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_presentation_reads import (
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
