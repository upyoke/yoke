"""Adopt preserved member QA when a later run enrolls its owner."""

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_run_membership_removals import membership_removals
from yoke_core.domain.deployment_run_member_set_aside import SET_ASIDE_REASON
from yoke_core.domain.deployment_run_qa_transfer import transfer_qa_on, qa_ownership_write


def adopt_set_aside_qa(conn, run_id, item_ids):
    ids = set(item_ids)
    if not ids:
        return
    predecessors = query_rows(
        conn,
        "SELECT old.id FROM deployment_runs old JOIN deployment_runs new "
        "ON old.project_id=new.project_id AND old.flow=new.flow "
        "AND old.target_environment_id=new.target_environment_id "
        "WHERE new.id=%s AND old.id<>new.id "
        "AND old.created_at<=new.created_at ORDER BY old.created_at,old.id",
        (run_id,),
    )
    with qa_ownership_write(conn):
        for row in predecessors:
            old_id = str(row[0])
            moving = {int(entry["item_id"]) for entry in membership_removals(conn, old_id)
                      if entry["reason"] == SET_ASIDE_REASON and int(entry["item_id"]) in ids}
            if moving:
                transfer_qa_on(conn, old_id=old_id, new_id=run_id,
                               moving=moving, include_run_qa=False)


def preserved_qa_selector(conn, run_id):
    """Return the detached member/group identities still awaiting enrollment."""
    from yoke_core.domain.deployment_qa_plan_groups import unattached_open_groups, group_marker

    members = {int(e["item_id"]) for e in membership_removals(conn, run_id)
               if e["reason"] == SET_ASIDE_REASON}
    groups = {g.group_id for g in unattached_open_groups(conn, run_id)} if members else set()

    def preserved(row):
        member = row.get("deployment_member_item_id")
        if member is not None:
            return int(member) in members
        marker = group_marker(row.get("execution_target_json") or row.get("execution_target"))
        return marker is not None and str(marker["group_id"]) in groups

    return preserved
