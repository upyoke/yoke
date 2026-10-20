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
    """The digest of every fact the approval gate's unlocked read depended on."""
    run_id = str(run_id)
    parts = (
        (
            _digest(
                "SELECT dr.status,dr.current_stage,dr.flow,dr.target_tier,"
                "dr.target_environment_id,dr.release_lineage,dr.created_by,"
                "df.stages FROM deployment_runs dr "
                "JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id=%s",
                "t.status",
            ),
            (run_id,),
        ),
        (
            _digest(
                "SELECT m.item_id,m.delivery_intent,i.status,i.title,"
                "i.project_id,i.project_sequence,i.workflow_id,"
                "i.workflow_version_id,i.workflow_posture "
                "FROM deployment_run_items m JOIN items i ON i.id=m.item_id "
                "WHERE m.run_id=%s",
                "t.item_id",
            ),
            (run_id,),
        ),
        (
            _digest(
                "SELECT r.id,r.status,r.resolution_action,r.consumed_at "
                "FROM decision_requests r JOIN deployment_run_items m "
                "ON r.subject_key=m.item_id::text || ':done' "
                "WHERE r.subject_type='item_transition' AND m.run_id=%s",
                "t.id",
            ),
            (run_id,),
        ),
        (
            _digest(
                "SELECT id,status,resolution_action,consumed_at "
                "FROM decision_requests "
                "WHERE subject_type='deployment_stage' AND subject_key=%s",
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
