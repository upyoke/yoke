"""Move open obligations to a ready receipt without rewriting frozen evidence."""

from yoke_core.domain.db_helpers import instant_parameter, query_rows, utc_now
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.deployment_qa_target_continuity import evidence_target_matches
from yoke_core.domain.deployment_qa_target_reads import _decode_stored_target
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    target_digest,
)
from yoke_core.domain.qa_latest_execution import latest_executions
from yoke_core.domain.qa_requirement_pass_currency import (
    passing_requirements_for_rows,
    recorded_execution_target_digest,
)


def rebind_subject(conn, *, subject, target):
    """Keep case ids; credit only passes that already prove the same destination.

    The caller holds the run lock. Executions, captures, runs and replacement
    pointers remain untouched; only the obligation follows the current receipt.
    """
    shared_plan_id = ((target.get("deployment") or {}).get("shared_plan") or {}).get(
        "plan_id"
    )
    rows = query_rows(
        conn,
        "SELECT * FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND COALESCE(deployment_member_item_id,0)=%s "
        "AND superseded_by_requirement_id IS NULL AND retracted_at IS NULL "
        "AND execution_target_digest IS DISTINCT FROM %s "
        "AND (%s::integer IS NULL OR plan_id=%s) ORDER BY id",
        (
            str(subject["id"]),
            str(subject["stage"]["name"]),
            int(subject.get("member_item_id") or 0),
            target_digest(target),
            shared_plan_id,
            shared_plan_id,
        ),
    )
    attempts = latest_executions(conn, [int(row["id"]) for row in rows])
    passing = passing_requirements_for_rows(conn, rows, attempts)
    rebound = []
    with savepoint(conn, "qa_deployment_target_refresh", owns=False):
        for row in rows:
            stored = _decode_stored_target(row["execution_target_json"])
            from yoke_core.domain.qa_plan_management import QaPlanError

            if (
                stored is None
                or target_digest(stored) != row["execution_target_digest"]
            ):
                raise QaPlanError(
                    f"qa_requirement_target_invalid: requirement {row['id']} has "
                    "invalid stored target evidence; preserve it and use sanctioned "
                    "retirement or supersession before materializing again"
                )
            requirement_id = int(row["id"])
            carried_digest = None
            if requirement_id in passing and evidence_target_matches(
                conn, str(subject["id"]), stored, target
            ):
                carried_digest = recorded_execution_target_digest(
                    attempts[requirement_id]["raw_result"]
                )
            conn.execute(
                "UPDATE qa_requirements SET execution_target_json=%s,"
                "execution_target_digest=%s,rebound_from_target_json=%s,"
                "rebound_from_digest=%s,rebound_at=%s,rebind_rationale=%s WHERE id=%s",
                (
                    canonical_target(target),
                    target_digest(target),
                    canonical_target(stored),
                    carried_digest,
                    instant_parameter(conn, utc_now()),
                    "Materialization follows the owning deployment's current target",
                    requirement_id,
                ),
            )
            rebound.append(requirement_id)
    return rebound
