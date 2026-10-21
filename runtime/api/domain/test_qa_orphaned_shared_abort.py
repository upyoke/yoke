"""A shared walk whose last attaching member left still settles.

Removing members deletes their run rows first, so no group resolves for the
shared plan any more. Stopping the walk must still settle it and hand its
pending capture review to the member that requested the walk.
"""

from __future__ import annotations

import json

from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _begin,
    _materialize,
    _seed,
)
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import advance_plan_execution
from yoke_core.domain.qa_plan_execution_store import select_plan_execution

NOW = "2026-10-21T00:00:00Z"


def _agent_reviewed(conn):
    conn.execute(
        "UPDATE qa_requirements SET method_id='browser-inspection',"
        "runner_id='browser_substrate',verdict_path='agent' "
        "WHERE deployment_run_id=%s AND method_id IS NOT NULL",
        (RUN,),
    )
    conn.commit()


def _capture_awaiting_review(conn, execution):
    requirement_id = int(execution["roster"][0]["requirement_id"])
    capture = int(
        conn.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,"
            "execution_status,case_outcome,raw_result,started_at,completed_at,"
            "created_at) VALUES(%s,'browser_substrate','method_case','captured',"
            "'needs_review','{}',%s,%s,%s) RETURNING id",
            (requirement_id, NOW, NOW, NOW),
        ).fetchone()["id"]
    )
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,created_at) VALUES(%s,'screenshot','image/png',%s,%s)",
        (capture, json.dumps({"backend": "local", "path": "/tmp/p.png"}), NOW),
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "runner_id": "browser_substrate",
            "verdict": "pending",
            "execution_status": "captured",
            "qa_run_id": capture,
            "run_id": capture,
        },
    )


def _orphaned_walk(conn):
    _seed(conn)
    _materialize(conn, MEMBERS[0])
    _agent_reviewed(conn)
    execution = _begin(conn, MEMBERS[0])
    _capture_awaiting_review(conn, execution)
    conn.execute("DELETE FROM deployment_run_items WHERE run_id=%s", (RUN,))
    conn.commit()
    return select_plan_execution(conn, execution["id"], lock=True)


def test_abort_settles_shared_walk_after_every_attaching_member_left(test_db):
    from yoke_core.domain.qa_plan_agent_review_wake import _answered_members

    execution = _orphaned_walk(test_db)

    assert _answered_members(test_db, execution) == [MEMBERS[0]]
    finish_plan_execution(
        test_db, execution, state="aborted", reason="deployment-member-removed"
    )

    actual = select_plan_execution(test_db, execution["id"], lock=False)
    assert actual["state"] == "aborted"


def test_a_later_member_removal_settles_the_orphaned_walk(test_db):
    """The driver sets aside a reopened member through the same removal."""
    from yoke_core.domain.qa_deployment_member_removal import (
        abort_removed_member_executions,
    )

    execution = _orphaned_walk(test_db)
    abort_removed_member_executions(test_db, run_id=RUN, item_ids=(9903,))
    test_db.commit()

    actual = select_plan_execution(test_db, execution["id"], lock=False)
    assert actual["state"] == "aborted"
