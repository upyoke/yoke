"""Adopt preserved member QA when a later run enrolls its owner."""

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_run_membership_removals import membership_removals, parse_membership_removals
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.deployment_run_member_set_aside import SET_ASIDE_REASONS
from yoke_core.domain.deployment_run_qa_transfer import transfer_qa_on, qa_ownership_write


def adopt_set_aside_qa(conn, run_id, item_ids):
    ids = set(item_ids)
    if not ids or not _column_exists(conn, "deployment_runs", "membership_removals"):
        return
    predecessors = query_rows(
        conn,
        "SELECT old.id,old.membership_removals FROM deployment_runs old JOIN deployment_runs new "
        "ON old.project_id=new.project_id AND old.flow=new.flow "
        "AND old.target_environment_id IS NOT DISTINCT FROM new.target_environment_id "
        "WHERE new.id=%s AND old.id<>new.id "
        "AND old.created_at<=new.created_at AND EXISTS ("
        "SELECT 1 FROM jsonb_array_elements(COALESCE(old.membership_removals,'[]')::jsonb) entry "
        "WHERE entry->>'reason'=ANY(%s) AND (entry->>'item_id')::bigint=ANY(%s)) "
        "ORDER BY old.created_at,old.id",
        (run_id, sorted(SET_ASIDE_REASONS), sorted(ids)),
    )
    with qa_ownership_write(conn):
        for row in predecessors:
            old_id = str(row[0])
            moving = {int(entry["item_id"]) for entry in parse_membership_removals(row[1], old_id)
                      if entry["reason"] in SET_ASIDE_REASONS and int(entry["item_id"]) in ids}
            if moving:
                transfer_qa_on(conn, old_id=old_id, new_id=run_id,
                               moving=moving, include_run_qa=False,
                               kept_requirement_ids=shadowed_requirements(
                                   conn, old_id=old_id, new_id=run_id, moving=moving))


def shadowed_requirements(conn, *, old_id, new_id, moving):
    """Historical member cases a live same-target release already owns.

    A live run on the adopting run's target (the adopting run included) that
    holds an open case with the same stage, member, plan, case and baseline is
    that case's current custody; the historical copy stays on its original
    run with its evidence, so one release owns each open case identity.
    """
    from yoke_core.domain.runs import TERMINAL_RUN_STATUSES

    rows = query_rows(
        conn,
        "SELECT DISTINCT old.id FROM qa_requirements old "
        "JOIN deployment_runs adopting ON adopting.id=%s "
        "JOIN qa_requirements live ON live.deployment_stage=old.deployment_stage "
        "AND live.deployment_member_item_id=old.deployment_member_item_id "
        "AND live.plan_id=old.plan_id AND live.plan_case_key=old.plan_case_key "
        "AND COALESCE(live.host_baseline,'')=COALESCE(old.host_baseline,'') "
        "AND live.superseded_by_requirement_id IS NULL AND live.retracted_at IS NULL "
        "JOIN deployment_runs owner ON owner.id=live.deployment_run_id "
        "AND owner.id<>old.deployment_run_id AND owner.project_id=adopting.project_id "
        "AND owner.flow=adopting.flow "
        "AND owner.target_environment_id IS NOT DISTINCT FROM adopting.target_environment_id "
        "AND owner.status<>ALL(%s) "
        "WHERE old.deployment_run_id=%s AND old.deployment_member_item_id=ANY(%s) "
        "AND old.deployment_stage IS NOT NULL AND old.plan_id IS NOT NULL",
        (new_id, sorted(TERMINAL_RUN_STATUSES), old_id, sorted(moving)),
    )
    return frozenset(int(row["id"]) for row in rows)


def preserved_qa_selector(conn, run_id, *, recorded_removals=None):
    """Select detached member/group QA that still awaits enrollment.

    ``recorded_removals`` is the run's ``membership_removals`` column when
    the caller already read it, so a batch reader adds no per-run read.
    """
    from yoke_core.domain.deployment_qa_plan_groups import unattached_open_groups, group_marker
    from yoke_core.domain.deployment_qa_presentation_facts import run_facts

    if recorded_removals is not None:
        removals = parse_membership_removals(recorded_removals, run_id)
    else:
        facts = run_facts(conn, run_id)
        removals = (
            parse_membership_removals(facts["membership_removals"], run_id)
            if facts is not None else membership_removals(conn, run_id)
        )
    members = {int(e["item_id"]) for e in removals
               if e["reason"] in SET_ASIDE_REASONS}
    groups = {g.group_id for g in unattached_open_groups(conn, run_id)} if members else set()

    def preserved(row):
        member = row.get("deployment_member_item_id")
        if member is not None:
            return int(member) in members
        marker = group_marker(row.get("execution_target_json") or row.get("execution_target"))
        return marker is not None and str(marker["group_id"]) in groups

    return preserved
