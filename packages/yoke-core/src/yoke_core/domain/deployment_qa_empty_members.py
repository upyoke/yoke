"""Remember materialized empty subjects until their QA inputs change.

The marker lives with the run's frozen selections. One batched input digest
invalidates it on target, selection, plan definition or requirement lineage
changes; verdicts and in-flight execution progress do not invalidate it.
"""

import json

from yoke_core.domain.deployment_run_qa_fingerprint import _digest

MARKER = "empty_qa_members"


def _inputs(conn, run_id):
    members = "SELECT item_id FROM deployment_run_items WHERE run_id=%s"
    projects = (f"SELECT project_id FROM items WHERE id IN ({members}) "
                "UNION SELECT project_id FROM deployment_runs WHERE id=%s")
    parts = [
        _digest(
            "SELECT release_lineage,artifact_identity,target_environment_id,"
            "bound_sources,requirement_snapshot::jsonb - 'empty_qa_members' AS snapshot "
            "FROM deployment_runs WHERE id=%s", "t.release_lineage",
        ),
        _digest(
            "SELECT m.item_id,m.requirement_snapshot,i.status FROM deployment_run_items m "
            "JOIN items i ON i.id=m.item_id WHERE m.run_id=%s", "t.item_id",
        ),
        _digest(f"SELECT * FROM qa_plan_item_attachments WHERE item_id IN ({members})",
                "t.item_id,t.plan_id,t.transition_id,t.qa_phase"),
        _digest(f"SELECT * FROM item_gate_satisfactions WHERE item_id IN ({members})",
                "t.item_id,t.obligation"),
        _digest(f"SELECT * FROM qa_plans WHERE project_id IN ({projects})", "t.id"),
        _digest("SELECT c.* FROM qa_plan_cases c JOIN qa_plans p ON p.id=c.plan_id "
                f"WHERE p.project_id IN ({projects})", "t.id"),
        _digest("SELECT q.* FROM qa_requirements q WHERE deployment_run_id=%s "
                f"OR (deployment_run_id IS NULL AND item_id IN ({members}))", "t.id"),
        _digest(f"SELECT * FROM environments WHERE project_id IN ({projects}) "
                "OR id IN (SELECT target_environment_id FROM deployment_runs WHERE id=%s)", "t.id"),
        _digest("SELECT * FROM deployment_stage_receipts WHERE run_id=%s", "t.id"),
    ]
    sql = f"SELECT md5(concat_ws(',',{','.join(parts)}))"
    return str(conn.execute(sql, (run_id,) * sql.count("%s")).fetchone()[0])


def empty_members(conn, run_id, stage):
    row = conn.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    snapshot = json.loads(row[0] or "{}")
    marker = snapshot.get(MARKER, {}).get(stage, {})
    if not marker or marker.get("inputs") != _inputs(conn, run_id):
        return set()
    return set(marker["members"])


def remember_empty_members(conn, run_id, stage, members):
    """Caller holds the run lock and commits this with materialization."""
    if not members:
        return
    marker = {"inputs": _inputs(conn, run_id), "members": sorted(members)}
    conn.execute(
        "UPDATE deployment_runs SET requirement_snapshot=(requirement_snapshot::jsonb "
        "|| jsonb_build_object('empty_qa_members', "
        "COALESCE(requirement_snapshot::jsonb->'empty_qa_members','{}'::jsonb) "
        "|| jsonb_build_object(%s::text,%s::jsonb)))::text WHERE id=%s",
        (stage, json.dumps(marker), run_id),
    )
