"""One digest of the state a run's approval gate reads before the run lock.

The approval gate reads its member decisions, batch and release contents
unlocked, then takes the ``deployment_runs`` row lock only to write. Taking
this fingerprint before those reads and again under the lock proves no
committed change landed in between: the run row and its flow's stages, the
membership with each member's status and workflow binding, the members' own
``done`` decision requests, and the stage's own decision requests. One
statement, whatever the run's size.
"""

from __future__ import annotations

from typing import Any


def _digest(select: str, order: str) -> str:
    return f"(SELECT md5(COALESCE(string_agg(t::text,'|' ORDER BY {order}),'')) FROM ({select}) t)"


def approval_inputs_fingerprint(conn: Any, run_id: str, stage: str) -> str:
    """The digest of every fact the approval gate's unlocked read depended on.

    Optional columns are read through ``to_jsonb``, where a column a schema
    has not created yet reads as null instead of failing the statement.
    """
    run_id = str(run_id)
    parts = (
        (
            _digest(
                "SELECT dr.status,dr.current_stage,dr.flow,"
                "to_jsonb(dr)->'target_tier' AS tier,"
                "to_jsonb(dr)->'target_environment_id' AS environment,"
                "to_jsonb(dr)->'release_lineage' AS lineage,"
                "to_jsonb(dr)->'created_by' AS creator,"
                "df.stages FROM deployment_runs dr "
                "JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id=%s",
                "t.status",
            ),
            (run_id,),
        ),
        (
            _digest(
                "SELECT m.item_id,to_jsonb(m)->'delivery_intent' AS intent,"
                "i.status,i.title,i.project_id,i.project_sequence,"
                "to_jsonb(i)->'workflow_id' AS workflow,"
                "to_jsonb(i)->'workflow_version_id' AS workflow_version,"
                "to_jsonb(i)->'workflow_posture' AS posture "
                "FROM deployment_run_items m JOIN items i ON i.id=m.item_id "
                "WHERE m.run_id=%s",
                "t.item_id",
            ),
            (run_id,),
        ),
        (
            _digest(
                "SELECT r.id,r.status,to_jsonb(r)->'resolution_action' AS action,"
                "to_jsonb(r)->'consumed_at' AS consumed "
                "FROM decision_requests r JOIN deployment_run_items m "
                "ON r.subject_key=m.item_id::text || ':done' "
                "WHERE r.subject_type='item_transition' AND m.run_id=%s",
                "t.id",
            ),
            (run_id,),
        ),
        (
            _digest(
                "SELECT r.id,r.status,to_jsonb(r)->'resolution_action' AS action,"
                "to_jsonb(r)->'consumed_at' AS consumed FROM decision_requests r "
                "WHERE r.subject_type='deployment_stage' AND r.subject_key=%s",
                "t.id",
            ),
            (f"{run_id}:{stage}",),
        ),
    )
    params: tuple[str, ...] = ()
    for _sql, values in parts:
        params += values
    row = conn.execute(
        f"SELECT md5(concat_ws(',',{','.join(sql for sql, _ in parts)}))",
        params,
    ).fetchone()
    return str(row[0])


__all__ = ["approval_inputs_fingerprint"]
