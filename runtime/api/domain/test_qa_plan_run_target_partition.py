"""Deployment-run plan reruns skip cases that already passed on the same target."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_qa_stage_execution import _seed_run, _stages
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config

RUN = "run-rerun-after-abort"
MEMBER = 9841
CASE_KEYS = ("first", "second", "third")


def _seed(conn: Any) -> None:
    plan = create_plan(
        conn, project="yoke", slug="rerun-after-abort", infer_target_environment=False
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "command",
                "instructions": f"run the {key} command",
                "expected_outcome": "the command passes",
                "method_config": {"command": "true"},
            }
            for position, key in enumerate(CASE_KEYS, 1)
        ],
    )
    stages = _stages(int(plan["id"]))
    stages[1]["cases"]["case_keys"] = list(CASE_KEYS)
    _seed_run(conn, run_id=RUN, stages=stages, members=(MEMBER,))
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
    )


def _begin(conn: Any) -> dict[str, Any]:
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id="rerun-session",
    )


def _ids(execution: dict[str, Any]) -> list[int]:
    return [int(row["requirement_id"]) for row in execution["roster"]]


def _pass(
    conn: Any,
    execution: dict[str, Any],
    ordinal: int,
    digest: str | None = None,
    *,
    evidence: bool = True,
) -> int:
    requirement_id = _ids(execution)[ordinal]
    config = conn.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()[0]
    raw = stamp_executed_method_config(
        "case passed",
        config,
        execution_target_digest=digest,
        conn=conn,
        requirement_id=requirement_id,
    )
    now = f"2026-09-14T00:0{2 + ordinal}:00Z"
    run_id = conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "raw_result,started_at,completed_at,created_at) VALUES "
        "(%s,'worktree_run','plan_case','pass',%s,%s,%s,%s) RETURNING id",
        (requirement_id, raw, now, now, now),
    ).fetchone()[0]
    if evidence:
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
            "artifact_handle,created_at) VALUES (%s,'log','application/json',%s,%s)",
            (run_id, f"evidence://case-{requirement_id}", now),
        )
    advance_plan_execution(
        conn,
        execution,
        ordinal=ordinal,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "pass",
            "case_outcome": "passed",
            "run_id": int(run_id),
        },
    )
    return requirement_id


def _abort(conn: Any, execution: dict[str, Any]) -> None:
    finish_plan_execution(conn, execution, state="aborted", reason="test abort")
    conn.commit()


def test_rerun_after_abort_rosters_only_unpassed_cases(test_db) -> None:
    _seed(test_db)
    aborted = _begin(test_db)
    roster = _ids(aborted)
    assert len(roster) == 3
    passed = _pass(test_db, aborted, 0)
    _abort(test_db, aborted)

    fresh = _begin(test_db)

    assert fresh["id"] != aborted["id"]
    assert _ids(fresh) == [row for row in roster if row != passed]
    assert [row["ordinal"] for row in fresh["roster"]] == [0, 1]
    assert fresh["cursor_ordinal"] == 0


def test_pass_recorded_on_another_target_still_runs(test_db) -> None:
    _seed(test_db)
    aborted = _begin(test_db)
    _pass(test_db, aborted, 0, digest="0" * 64)
    _abort(test_db, aborted)

    assert _ids(_begin(test_db)) == _ids(aborted)


def test_pass_without_evidence_still_runs(test_db) -> None:
    _seed(test_db)
    aborted = _begin(test_db)
    _pass(test_db, aborted, 0, evidence=False)
    _abort(test_db, aborted)

    assert _ids(_begin(test_db)) == _ids(aborted)


def test_live_execution_keeps_its_roster(test_db) -> None:
    _seed(test_db)
    live = _begin(test_db)
    _pass(test_db, live, 0)
    test_db.commit()

    resumed = _begin(test_db)

    assert resumed["id"] == live["id"]
    assert _ids(resumed) == _ids(live)


def test_every_case_passed_keeps_the_whole_roster(test_db) -> None:
    _seed(test_db)
    aborted = _begin(test_db)
    for ordinal in range(3):
        _pass(test_db, aborted, ordinal)
    _abort(test_db, aborted)

    assert _ids(_begin(test_db)) == _ids(aborted)


def test_multi_host_rerun_after_abort_moves_to_the_next_host(
    test_db, tmp_path, monkeypatch
) -> None:
    from runtime.api.domain import test_qa_member_machine_partitions as hosts

    hosts._seed(test_db, tmp_path, monkeypatch)
    aborted = hosts._begin(test_db)
    assert [case["case_key"] for case in aborted["roster"]] == [hosts.MACHINES[0]]
    _pass(test_db, aborted, 0)
    _abort(test_db, aborted)

    fresh = hosts._begin(test_db)

    assert [case["case_key"] for case in fresh["roster"]] == [hosts.MACHINES[1]]
    assert fresh["remaining_requirement_count"] == 0
