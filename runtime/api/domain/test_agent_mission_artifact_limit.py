"""Artifact-volume boundary for exploratory mission evidence."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.machine_qa_execution import AGENT_MISSION_ARTIFACT_LIMIT
from yoke_core.domain.handlers.qa_browser_writes import handle_qa_artifact_add
from yoke_core.domain.qa_artifact_ops import (
    QaArtifactLimitError,
    ensure_artifact_capacity,
)


def _mission_run(conn, *, item_id: int) -> tuple[int, int]:
    insert_item(conn, id=item_id, title="Explore installation", workflow_id="issue")
    now = "2026-08-20T00:00:00Z"
    requirement_id = int(
        conn.execute(
            "INSERT INTO qa_requirements("
            "item_id,qa_kind,qa_phase,blocking_mode,requirement_source,"
            "method_id,method_name,runner_id,verdict_path,instructions,"
            "expected_outcome,method_config,created_at) "
            "VALUES(%s,'exploratory','verification','blocking','explicit',"
            "'exploratory-mission','Exploratory mission','agent_mission',"
            "'agent','Explore.','Report findings.',%s,%s) RETURNING id",
            (item_id, json.dumps({"executor": "informed_subagent"}), now),
        ).fetchone()[0]
    )
    run_id = int(
        conn.execute(
            "INSERT INTO qa_runs("
            "qa_requirement_id,performed_by,qa_kind,execution_status,"
            "case_outcome,created_at) "
            "VALUES(%s,'agent_mission','exploratory','captured',"
            "'needs_review',%s) RETURNING id",
            (requirement_id, now),
        ).fetchone()[0]
    )
    return requirement_id, run_id


def _insert_artifacts(conn, *, run_id: int, count: int) -> None:
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO qa_artifacts("
            "qa_run_id,artifact_type,artifact_handle,metadata,created_at) "
            "VALUES(%s,'screenshot',%s,%s,'2026-08-20T00:00:00Z')",
            [
                (
                    run_id,
                    json.dumps(
                        {
                            "backend": "local",
                            "path": f"/tmp/proof-{index}.png",
                        }
                    ),
                    json.dumps({"finding": f"finding-{index}"}),
                )
                for index in range(count)
            ],
        )


def _limit_message(run_id: int) -> str:
    attempted = AGENT_MISSION_ARTIFACT_LIMIT + 1
    return (
        f"exploratory mission artifact limit reached for run {run_id}: "
        f"attachment {attempted} was not added; limit is "
        f"{AGENT_MISSION_ARTIFACT_LIMIT}. Keep only deliberate proof of findings."
    )


def test_limit_allows_final_artifact_and_explains_rejected_next_attempt() -> None:
    with test_database() as conn:
        requirement_id, run_id = _mission_run(conn, item_id=4611)
        _insert_artifacts(
            conn,
            run_id=run_id,
            count=AGENT_MISSION_ARTIFACT_LIMIT - 1,
        )
        assert ensure_artifact_capacity(conn, run_id) == requirement_id
        _insert_artifacts(conn, run_id=run_id, count=1)
        conn.commit()

        with pytest.raises(QaArtifactLimitError) as raised:
            ensure_artifact_capacity(conn, run_id)
        assert str(raised.value) == _limit_message(run_id)
        conn.rollback()

        outcome = handle_qa_artifact_add(
            FunctionCallRequest(
                function="qa.artifact.add",
                actor=ActorContext(actor_id="1", session_id="mission-owner"),
                target=TargetRef(
                    kind="qa_requirement",
                    qa_requirement_id=requirement_id,
                ),
                payload={
                    "run_id": run_id,
                    "artifact_type": "screenshot",
                    "artifact_handle": {
                        "backend": "local",
                        "path": "/tmp/rejected-proof.png",
                    },
                },
            )
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "policy_violation"
        assert outcome.error.message == _limit_message(run_id)
        stored = conn.execute(
            "SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id=%s",
            (run_id,),
        ).fetchone()[0]
        assert int(stored) == AGENT_MISSION_ARTIFACT_LIMIT
