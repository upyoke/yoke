"""Live-run status facts stay complete when they are read as a set.

The report used to ask receipts, red verdicts, decisions, and
outstanding/total once per live run. These tests hold the visible
sentence to the same answers and show that the SQL count for that
read does not grow as a sequence of per-run queries.
"""

from __future__ import annotations

import time
from typing import Any

from runtime.api.steering_fleet_test_helpers import (
    NOW,
    PROJECT_ID,
    compose,
    seed_steering_scope,
)
from yoke_core.domain.steering_fleet_report_deployment_runs import run_progress
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body


STARTED = "2026-08-26T08:00:00Z"
OLDER = "2026-08-26T07:00:00Z"
STAGE_QA = "item-qa"
STAGE_RELEASE = "hosted-release"


class _CountingConnection:
    def __init__(self, inner: Any) -> None:
        self._conn = inner
        self.statement_count = 0

    def execute(self, sql: str, params: tuple = ()) -> Any:
        self.statement_count += 1
        return self._conn.execute(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _seed_run(
    conn,
    *,
    run_id: str,
    stage: str = STAGE_QA,
    status: str = "executing",
    receipt_at: str | None = STARTED,
    started_at: str = STARTED,
) -> None:
    conn.execute(
        "INSERT INTO deployment_runs"
        "(id,project_id,flow,status,current_stage,created_at,started_at) "
        "VALUES (%s,1,'prod-release',%s,%s,%s,%s)",
        (run_id, status, stage, started_at, started_at),
    )
    if receipt_at is None:
        return
    conn.execute(
        "INSERT INTO deployment_stage_receipts"
        "(run_id,stage_name,attempt_number,correlation_id,target_kind,"
        "target_name,status,executor,created_at) "
        "VALUES (%s,%s,1,%s,'environment','prod','running','operator',%s)",
        (run_id, stage, f"{run_id}:{stage}:1", receipt_at),
    )


def _seed_requirement(
    conn, *, run_id: str, requirement_id: int, member_item_id: int | None,
    waived_at: str | None = None, superseded_by: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO qa_requirements"
        "(id,deployment_run_id,deployment_stage,deployment_member_item_id,"
        "qa_kind,qa_phase,blocking_mode,requirement_source,created_at,"
        "waived_at,superseded_by_requirement_id) "
        "VALUES (%s,%s,%s,%s,'browser','post_deploy','blocking','flow_derived',"
        "%s,%s,%s)",
        (
            requirement_id, run_id, STAGE_QA, member_item_id, STARTED,
            waived_at, superseded_by,
        ),
    )


def _record_verdict(conn, *, requirement_id: int, verdict: str, at: str = STARTED) -> None:
    conn.execute(
        "INSERT INTO qa_runs"
        "(qa_requirement_id,performed_by,qa_kind,verdict,created_at,completed_at) "
        "VALUES (%s,'agent','browser',%s,%s,%s)",
        (requirement_id, verdict, at, at),
    )


def _resolve_decision(conn, *, run_id: str, request_id: int, stage: str, action: str) -> None:
    conn.execute(
        "INSERT INTO decision_requests"
        "(id,kind,subject_type,subject_key,project_id,status,"
        "resolution_action,resolved_at,approval_mode,created_at) "
        "VALUES (%s,'deployment_stage_approval','deployment_stage',%s,1,"
        "'resolved',%s,%s,'any',%s)",
        (request_id, f"{run_id}:{stage}", action, STARTED, STARTED),
    )


def test_a_run_without_a_stage_receipt_ages_from_the_run_clock(test_db) -> None:
    conn = seed_steering_scope(test_db)
    _seed_run(conn, run_id="run-20260826-010", receipt_at=None)
    conn.commit()

    run = compose(conn).deployment_runs[0]
    assert run.stage_seconds == 4 * 3600


def test_waived_and_superseded_requirements_are_not_red(test_db) -> None:
    conn = seed_steering_scope(test_db)
    _seed_run(conn, run_id="run-20260826-011")
    _seed_requirement(conn, run_id="run-20260826-011", requirement_id=911, member_item_id=1)
    _seed_requirement(
        conn, run_id="run-20260826-011", requirement_id=912, member_item_id=1,
        waived_at=STARTED,
    )
    _seed_requirement(
        conn, run_id="run-20260826-011", requirement_id=913, member_item_id=1,
        superseded_by=911,
    )
    _record_verdict(conn, requirement_id=911, verdict="fail")
    _record_verdict(conn, requirement_id=912, verdict="fail")
    _record_verdict(conn, requirement_id=913, verdict="fail")
    conn.commit()

    run = compose(conn).deployment_runs[0]
    assert [red.requirement_id for red in run.red] == [911]
    assert run.outstanding == 1
    assert run.total_blocking == 1


def test_a_later_pass_replaces_an_earlier_fail_on_the_same_requirement(test_db) -> None:
    conn = seed_steering_scope(test_db)
    _seed_run(conn, run_id="run-20260826-012")
    _seed_requirement(conn, run_id="run-20260826-012", requirement_id=921, member_item_id=1)
    _record_verdict(conn, requirement_id=921, verdict="fail", at=OLDER)
    _record_verdict(conn, requirement_id=921, verdict="pass", at=STARTED)
    conn.commit()

    run = compose(conn).deployment_runs[0]
    assert run.red == ()
    assert run.outstanding == 0
    assert run.total_blocking == 1


def test_simultaneous_runs_keep_per_run_receipts_decisions_and_reds(test_db) -> None:
    conn = seed_steering_scope(test_db)
    _seed_run(conn, run_id="run-20260826-021", stage=STAGE_QA)
    _seed_run(conn, run_id="run-20260826-022", stage=STAGE_RELEASE)
    _seed_requirement(conn, run_id="run-20260826-021", requirement_id=931, member_item_id=1)
    _seed_requirement(conn, run_id="run-20260826-022", requirement_id=932, member_item_id=2)
    _record_verdict(conn, requirement_id=931, verdict="fail")
    _record_verdict(conn, requirement_id=932, verdict="error")
    _resolve_decision(
        conn, run_id="run-20260826-021", request_id=8401, stage=STAGE_QA, action="approve",
    )
    _resolve_decision(
        conn, run_id="run-20260826-022", request_id=8402,
        stage="earlier-gate", action="approve",
    )
    conn.commit()

    report = compose(conn)
    by_id = {row.run_id: row for row in report.deployment_runs}
    qa = by_id["run-20260826-021"]
    release = by_id["run-20260826-022"]
    assert qa.stage == STAGE_QA
    assert qa.red[0].requirement_id == 931
    assert qa.answered_decision is not None
    assert qa.answered_decision.request_id == 8401
    assert release.stage == STAGE_RELEASE
    assert release.red[0].requirement_id == 932
    assert release.answered_decision is None
    body = report_body(report)
    assert "run-20260826-021" in body and "run-20260826-022" in body
    projected = report_dict(report)
    assert {row["run_id"] for row in projected["deployment_runs"]} == {
        "run-20260826-021",
        "run-20260826-022",
    }


def _seed_scaled_run(conn, index: int) -> None:
    run_id = f"run-20260826-{index:03d}"
    _seed_run(conn, run_id=run_id, stage=STAGE_RELEASE)
    _seed_requirement(
        conn, run_id=run_id, requirement_id=2000 + index, member_item_id=1,
    )
    _record_verdict(conn, requirement_id=2000 + index, verdict="pass")
    _resolve_decision(
        conn, run_id=run_id, request_id=9000 + index,
        stage=STAGE_RELEASE, action="approve",
    )


def _progress_cost(conn) -> tuple[int, float, int]:
    wrapped = _CountingConnection(conn)
    started = time.perf_counter()
    rows = run_progress(wrapped, project_id=PROJECT_ID, now=NOW)
    elapsed = time.perf_counter() - started
    return wrapped.statement_count, elapsed, len(rows)


def test_query_count_does_not_grow_as_a_sequence_of_per_run_reads(test_db) -> None:
    conn = seed_steering_scope(test_db)
    costs: dict[int, tuple[int, float]] = {}
    seeded = 0
    for target in (1, 10, 30):
        for index in range(seeded + 1, target + 1):
            _seed_scaled_run(conn, index)
        conn.commit()
        seeded = target
        queries, elapsed, n_rows = _progress_cost(conn)
        assert n_rows == target
        costs[target] = (queries, elapsed)
    assert costs[1][0] == costs[10][0] == costs[30][0], (
        f"query count scaled with live runs: {costs}"
    )
    assert costs[1][0] > 0
