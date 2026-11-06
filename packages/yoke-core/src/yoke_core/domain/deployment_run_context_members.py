"""Reconcile reworking members before execution-context composition."""

from yoke_core.domain.deployment_run_member_set_aside import set_aside_reworking_members


def set_aside_context_members(conn, run_id):
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (run_id,)
    ).fetchall()
    return set_aside_reworking_members(conn, run_id, (row[0] for row in rows))
