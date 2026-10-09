"""Persist an owner-bound completed-delivery fact for dependency fixtures."""

import json

from yoke_core.domain.gate_satisfaction_schema import create_gate_satisfaction_tables


def stamp_completed_members(conn, run_id):
    create_gate_satisfaction_tables(conn)
    rows = conn.execute(
        "SELECT i.id,i.project_id,dr.project_id,e.id,e.name FROM items i "
        "JOIN deployment_run_items m ON m.item_id=i.id "
        "JOIN deployment_runs dr ON dr.id=m.run_id "
        "JOIN environments target ON target.id=dr.target_environment_id "
        "JOIN environments e ON e.name=target.name AND e.project_id=i.project_id "
        "WHERE dr.id=%s",
        (run_id,),
    ).fetchall()
    for item_id, project_id, run_project, environment_id, environment in rows:
        entry = {
            "item_id": int(item_id),
            "project_id": int(project_id),
            "member_item_id": int(item_id),
            "run_project_id": int(run_project),
            "run_id": run_id,
            "environment_id": int(environment_id),
            "environment": environment,
            "candidate": "a" * 40,
            "source": "run_membership",
        }
        conn.execute(
            "INSERT INTO item_gate_satisfactions(item_id,obligation,rung_id,target_status,facts,recorded_at) "
            "VALUES (%s,'delivery_evidence','deployment_run_succeeded','done',%s,%s) "
            "ON CONFLICT(item_id,obligation) DO UPDATE SET facts=EXCLUDED.facts",
            (
                item_id,
                json.dumps({"completed_deliveries": [entry]}),
                "2026-09-03T12:00:00Z",
            ),
        )
