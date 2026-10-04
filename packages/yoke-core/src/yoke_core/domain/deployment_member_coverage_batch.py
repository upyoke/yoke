"""Set-based run coverage using one flow, source record and completion read."""

from yoke_core.domain.schema_read_scope import shared_read
from yoke_core.domain.deployment_item_flow_resolution import (
    item_completion_flow_facts,
    membership_closes_item,
)
from yoke_core.domain.deployment_run_project_sources import (
    run_source_facts,
    recorded_source_sha,
)
from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_core.domain.qa_item_stage_plan_gate import item_scoped_qa_stage_names
from yoke_core.domain import db_backend


def member_run_coverages(conn, *, run_id, item_ids):
    ids = tuple(dict.fromkeys(int(value) for value in item_ids))
    return shared_read(
        conn, ("coverage", str(run_id), ids), lambda: _resolve(conn, str(run_id), ids)
    )


def _resolve(conn, run_id, ids):
    from yoke_core.domain.deployment_member_run_coverage import MemberRunCoverage

    if not ids:
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    run = run_source_facts(conn, run_id)
    if run is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    rows = conn.execute(
        f"SELECT id,project_id FROM items WHERE id IN ({','.join(marker for _ in ids)})",
        ids,
    ).fetchall()
    projects = {int(row[0]): int(row[1]) for row in rows}
    for item_id in ids:
        if item_id not in projects:
            raise LookupError(f"item {item_id!r} not found")
    facts = item_completion_flow_facts(conn, ids)
    refs = render_item_ref_lookup(conn, ids)
    stages = item_scoped_qa_stage_names(run["stages"])
    return {
        item_id: MemberRunCoverage(
            item_ref=refs(item_id),
            run_id=run_id,
            run_flow=str(run["flow"] or ""),
            completion_flow=facts[item_id].flow if item_id in facts else "",
            item_scoped_stages=stages,
            closes=membership_closes_item(
                run_flow=str(run["flow"] or ""),
                completion_flow=facts[item_id].flow if item_id in facts else "",
                run_project_id=int(run["project_id"]),
                item_project_id=projects[item_id],
                source_sha=recorded_source_sha(run, projects[item_id]),
            ),
        )
        for item_id in ids
    }


def final_open_member_ids(conn, run_id):
    """Mutable member intent/status is read together, never cached."""
    from yoke_core.domain.deployment_run_composition_freeze import (
        DELIVERY_INTENT_PROGRESS,
    )
    from yoke_core.domain.workflow_runtime import ENGINE_TERMINAL_STAGE_IDS
    from yoke_core.domain.workflow_delivery_binding_validation import (
        COMPLETED_ITEM_STAGE_ID,
    )

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT dri.item_id,COALESCE(dri.delivery_intent,''),i.status "
        "FROM deployment_run_items dri JOIN items i ON i.id=dri.item_id "
        f"WHERE dri.run_id={marker} ORDER BY dri.item_id",
        (run_id,),
    ).fetchall()
    return tuple(
        int(row[0])
        for row in rows
        if str(row[1]) != DELIVERY_INTENT_PROGRESS
        and str(row[2]) not in ENGINE_TERMINAL_STAGE_IDS | {COMPLETED_ITEM_STAGE_ID}
    )
