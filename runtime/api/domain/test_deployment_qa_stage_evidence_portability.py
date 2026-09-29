"""A human-accepted stage never asks for review against placeholder evidence."""

import json
from typing import Any

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_stage_human_review import _human_actor
from yoke_core.domain import qa_evidence_portability
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_outcome import OUTCOME_BLOCKED
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)

RUN = "run-portable-stage"
CAPTURE_MACHINE_HANDLE = {"backend": "local", "path": "/Users/capture/shot.png"}


def _status(test_db) -> dict:
    return deployment_qa_stage_status(
        test_db, run_id=RUN, stage_name="item-qa", member_item_id=None
    )


def _complete_case_with_local_capture(conn: Any, execution: dict) -> tuple[int, int]:
    """Pass the one case with a screenshot recorded on the capture machine."""
    requirement_id = int(execution["roster"][0]["requirement_id"])
    now = "2026-09-29T00:02:00Z"
    run_id = int(
        conn.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
            "started_at,completed_at,created_at) "
            "VALUES (%s,'browser_substrate','plan_case','pass',%s,%s,%s) RETURNING id",
            (requirement_id, now, now, now),
        ).fetchone()[0]
    )
    artifact_id = int(
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
            "artifact_handle,created_at) "
            "VALUES (%s,'screenshot','image/png',%s,%s) RETURNING id",
            (run_id, json.dumps(CAPTURE_MACHINE_HANDLE), now),
        ).fetchone()[0]
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "pass",
            "case_outcome": "passed",
            "run_id": run_id,
        },
    )
    finish_plan_execution(conn, execution, state="completed", reason="test-complete")
    return requirement_id, artifact_id


def _acceptance_rows(test_db) -> tuple[int, int]:
    runs = test_db.execute(
        "SELECT COUNT(*) FROM qa_runs r JOIN qa_requirements q "
        "ON q.id=r.qa_requirement_id WHERE q.deployment_run_id=%s "
        "AND q.qa_kind='deployment_stage_acceptance'",
        (RUN,),
    ).fetchone()[0]
    requests = test_db.execute(
        "SELECT COUNT(*) FROM decision_requests WHERE kind='qa_needs_review'"
    ).fetchone()[0]
    return int(runs), int(requests)


def test_capture_machine_evidence_blocks_the_request_until_rehomed(
    test_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        qa_evidence_portability, "administered_elsewhere_env", lambda: "prod-db-admin"
    )
    reviewer = 9797
    _human_actor(test_db, reviewer)
    stages = _stages(
        _plan(test_db, "portable-release-smoke"),
        verdict={
            "mode": "required_human",
            "reviewers": {"mode": "all", "roles": [], "actors": [reviewer]},
        },
    )
    stages[1]["scope"] = "run"
    _seed_run(test_db, run_id=RUN, stages=stages, members=())
    materialize_deployment_qa_stage(
        test_db, deployment_run_id=RUN, deployment_stage="item-qa"
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        actor_id="2",
        session_id="run-qa",
    )
    requirement_id, artifact_id = _complete_case_with_local_capture(
        test_db, execution
    )

    blocked = _status(test_db)

    assert blocked["outcome"] == OUTCOME_BLOCKED
    assert blocked["request_id"] is None
    assert (
        f"yoke qa artifact rehome --requirement-id {requirement_id} "
        f"--artifact-id {artifact_id}"
    ) in " ".join(blocked["reasons"])
    # The undetermined acceptance was withdrawn with the refused request, so
    # nothing claims a human review is pending.
    assert _acceptance_rows(test_db) == (0, 0)

    test_db.execute(
        "UPDATE qa_artifacts SET artifact_handle=%s WHERE id=%s",
        (json.dumps({"backend": "s3", "bucket": "b", "key": "k/shot.png"}), artifact_id),
    )
    test_db.commit()

    pending = _status(test_db)

    assert not pending["accepted"]
    assert pending["request_id"] is not None
    assert _acceptance_rows(test_db) == (1, 1)
