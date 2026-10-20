"""Retire redundant member copies when their shared plan group materializes."""

import json

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_execution_environment_target import canonical_target
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.qa_plan_attachment_retract import retract_requirements
from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
from yoke_core.domain.qa_plan_management import QaPlanError


def retire_member_copies(conn, subject, target, shared_ids, *, members):
    """Keep captures as history; never rewrite a roster somebody is executing.

    ``members`` attach this exact group, read before the run lock.
    """
    rows = query_rows(
        conn,
        "SELECT q.id,q.deployment_member_item_id,q.execution_target_json "
        "FROM qa_requirements q WHERE q.deployment_run_id=%s AND q.deployment_stage=%s "
        "AND q.plan_id=%s AND q.deployment_member_item_id IS NOT NULL "
        f"AND NOT {settled_obligation_sql(conn, 'q')}",
        (subject["id"], subject["stage"]["name"], subject["shared_plan"]["plan_id"]),
    )
    if not rows:
        return
    members = set(members)
    redundant = []
    owners = set()
    for row in rows:
        member = int(row["deployment_member_item_id"])
        if member not in members:
            continue
        previous = json.loads(str(row["execution_target_json"] or "{}"))
        deployment = previous.get("deployment")
        if not isinstance(deployment, dict):
            raise QaPlanError(
                f"shared_plan_duplicate_target_missing: requirement {row['id']} has no "
                "frozen target; repair that requirement's binding before materializing the shared group"
            )
        deployment.pop("member_item_id", None)
        deployment["shared_plan"] = subject["shared_plan"]
        if canonical_target(previous) == canonical_target(target):
            redundant.append(int(row["id"]))
            owners.add(member)
    if not redundant:
        return
    live = query_rows(
        conn,
        "SELECT id,deployment_member_item_id FROM qa_plan_executions "
        "WHERE deployment_run_id=%s AND deployment_stage=%s "
        f"AND state IN ({LIVE_PLAN_EXECUTION_SQL})",
        (subject["id"], subject["stage"]["name"]),
    )
    for execution in live:
        if execution["deployment_member_item_id"] in owners:
            raise QaPlanError(
                f"shared_plan_duplicate_execution_live: execution {execution['id']} owns "
                "the member copies; have its owner finish or abort that execution, then "
                "retry the same scoped plan command. No requirements were retired."
            )
    retract_requirements(
        conn,
        redundant,
        reason=f"Shared plan {subject['shared_plan']['plan_id']} requirements {sorted(shared_ids)} now own this group's verdict; member copies remain historical evidence",
        source="shared_plan_group",
    )

    # A member whose entire case set moved to groups no longer owns a private
    # aggregate acceptance. Preserve it as history alongside its old cases.
    aggregates = []
    for member in owners:
        remaining = conn.execute(
            "SELECT 1 FROM qa_requirements q WHERE q.deployment_run_id=%s AND q.deployment_stage=%s "
            "AND q.deployment_member_item_id=%s AND q.qa_kind<>'deployment_stage_acceptance' "
            f"AND NOT {settled_obligation_sql(conn, 'q')} LIMIT 1",
            (subject["id"], subject["stage"]["name"], member),
        ).fetchone()
        if remaining is None:
            aggregates.extend(
                int(row["id"])
                for row in query_rows(
                    conn,
                    "SELECT q.id FROM qa_requirements q WHERE q.deployment_run_id=%s "
                    "AND q.deployment_stage=%s AND q.deployment_member_item_id=%s "
                    f"AND q.qa_kind='deployment_stage_acceptance' AND NOT {settled_obligation_sql(conn, 'q')}",
                    (subject["id"], subject["stage"]["name"], member),
                )
            )
    retract_requirements(
        conn,
        aggregates,
        reason="The member's attached shared groups now own stage acceptance",
        source="shared_plan_group",
    )
