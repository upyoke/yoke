"""Retire an unsuccessful deployment's QA on its closing transaction."""

from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_latest_execution import latest_execution_id_sql
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.qa_plan_attachment_retract import retract_requirements
from yoke_core.domain.qa_plan_execution_abort_state import abort_request
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_schema import (
    LIVE_PLAN_EXECUTION_SQL,
    TERMINAL_PLAN_EXECUTION_STATES,
)
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
from yoke_core.domain.schema_common import _table_exists


def inherited_qa_sql(alias: str = "") -> str:
    """Transferred ownership differs from the immutable starting release."""
    prefix = f"{alias}." if alias else ""
    return (
        f"COALESCE(NULLIF({prefix}execution_target_json,''),'{{}}')::jsonb "
        f"#>> '{{deployment,run_id}}' <> {prefix}deployment_run_id"
    )


def preserves_inherited_qa(conn: Any, run_id: str) -> bool:
    """A failed successor keeps its inherited work until retry or takeover."""
    row = conn.execute(
        "SELECT 1 FROM deployment_runs WHERE id=%s AND status='failed' "
        "AND supersedes_run_id IS NOT NULL AND superseded_by_run_id IS NULL",
        (run_id,),
    ).fetchone()
    return row is not None


def failed_qa_owner_sql(conn: Any, alias: str) -> str:
    """Failed ownership exists only where inherited QA records exist."""
    if not _table_exists(conn, "qa_requirements"):
        return "false"
    return (
        f"{alias}.status='failed' AND {alias}.supersedes_run_id IS NOT NULL "
        f"AND {alias}.superseded_by_run_id IS NULL AND EXISTS ("
        f"SELECT 1 FROM qa_requirements q WHERE q.deployment_run_id={alias}.id "
        f"AND q.retracted_at IS NULL AND ({inherited_qa_sql('q')}))"
    )


def settle_unsuccessful_run(conn: Any, run_id: str, *, reason: str) -> bool:
    """Abort live cursors and retract unfulfilled run obligations without committing.

    A cursor already settling through a recorded abort is left to that abort.
    """
    preserve = preserves_inherited_qa(conn, run_id)
    failed = conn.execute("SELECT status FROM deployment_runs WHERE id=%s", (run_id,)).fetchone()
    failed = failed is not None and str(failed[0]) == "failed"
    group_sql = "COALESCE(NULLIF(execution_target_json,''),'{}')::jsonb #>> '{deployment,shared_plan,group_id}' IS NOT NULL"
    ordinary = f"AND NOT COALESCE(({inherited_qa_sql()}),false) " if preserve else ""
    ordinary += f"AND NOT ({group_sql}) " if failed else ""
    executions = [
        lock_plan_execution(conn, str(row["id"]))
        for row in (
            query_rows(
                conn,
                "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
                f"AND state IN ({LIVE_PLAN_EXECUTION_SQL}) {ordinary}ORDER BY id",
                (run_id,),
            )
            if _table_exists(conn, "qa_plan_executions")
            else []
        )
    ]
    # An execution already under a cooperative abort keeps its held host
    # until its own cleanup proof settles it (a removed member's walk, say).
    executions = [
        e
        for e in executions
        if e["state"] not in TERMINAL_PLAN_EXECUTION_STATES and abort_request(e) is None
    ]
    # Clear queue intents together before a released host can grant the next
    # cursor from this same closed run.
    for execution in executions:
        conn.execute(
            "UPDATE qa_plan_executions SET release_reason=NULL WHERE id=%s",
            (execution["id"],),
        )
    for execution in executions:
        finish_plan_execution(
            conn, execution, state="aborted", reason=reason, commit=False
        )
    if not _table_exists(conn, "qa_requirements"):
        return preserve
    rows = query_rows(
        conn,
        "SELECT r.id FROM qa_requirements r WHERE r.deployment_run_id=%s "
        + (f"AND NOT COALESCE(({inherited_qa_sql('r')}),false) " if preserve else "")
        + f"AND NOT {settled_obligation_sql(conn, 'r')} "
        + (f"AND NOT ({group_sql.replace('execution_target_json', 'r.execution_target_json')}) " if failed else "")
        + "AND NOT EXISTS (SELECT 1 FROM qa_runs qr "
        f"WHERE qr.id=({latest_execution_id_sql('r.id')}) AND qr.verdict='pass')",
        (run_id,),
    )
    retract_requirements(
        conn, [int(row["id"]) for row in rows], reason=reason, source="deployment_run"
    )
    return preserve


def restore_retry_obligations(conn: Any, run_id: str) -> None:
    """Reinstate only this run's automatic retirements on an authorized retry.

    A member removed since the failure owes the retry nothing, so only run
    rows, current members' rows and plan groups some member still attaches
    come back.
    """
    from importlib import import_module

    migration = import_module("yoke_core.domain.migrations.0094_delete_post_deploy_item_qa_copies")
    predicate = migration.OLD_MODEL_RUNS.replace(migration.UNFINISHED, "('failed')")
    if str(run_id) in {str(row[0]) for row in conn.execute(predicate).fetchall()}:
        raise ValueError(
            f"old_model_plan_run_retry_refused: run {run_id} used obsolete plan copies; "
            "create a new release run with `yoke deployment-runs create --help` "
            "instead of retrying this run"
        )
    if _table_exists(conn, "qa_requirements"):
        from yoke_core.domain.deployment_qa_plan_groups import (
            attached_plans,
            run_groups,
        )

        plans = attached_plans(conn, run_id)
        orphaned = [g.digest for g in run_groups(conn, run_id) if not plans.get(g.plan_id)]
        conn.execute(
            "UPDATE qa_requirements SET retracted_at=NULL, "
            "retraction_rationale=NULL, retraction_source=NULL "
            "WHERE deployment_run_id=%s AND retraction_source='deployment_run' "
            f"AND NOT COALESCE(({inherited_qa_sql()}),false) "
            "AND NOT (COALESCE(execution_target_digest,'')=ANY(%s)) "
            "AND (deployment_member_item_id IS NULL OR deployment_member_item_id IN "
            "(SELECT item_id FROM deployment_run_items WHERE run_id=%s))",
            (run_id, orphaned, run_id),
        )
