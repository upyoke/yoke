"""Item plan runs skip cases passed at the candidate and run one target at a time."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.fixtures.backlog import insert_item_worktree
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.session_holdings import insert_item_claim
from yoke_core.domain.qa_catalog_schema import seed_builtin_qa_methods
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    canonical,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config
from yoke_core.domain.schema_init_tables import create_governed_tables

ITEM_ID = 4721
TRANSITION = "reviewing-implementation"
CANDIDATE = "a" * 40
SESSION = "partition-session"
BRANCH = "mixed-targets"

CI_CASE = {
    "case_key": "full-suite",
    "position": 1,
    "method_id": "command",
    "instructions": "Run the full suite.",
    "expected_outcome": "The suite passes.",
    "method_config": {"command": "true"},
}
MISSION_CASE = {
    "case_key": "receiving-mission",
    "position": 1,
    "method_id": "exploratory-mission",
    "instructions": "Walk the receiving path against production.",
    "expected_outcome": "Return ranked findings.",
    "method_config": {"executor": "informed_subagent"},
    "host_baselines": ["fresh-host"],
}


def _mixed_roster(conn: Any, tmp_path: Any, monkeypatch: Any) -> dict[str, Any]:
    create_governed_tables(conn)
    seed_builtin_qa_methods(conn)
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'prod','https://prod.example.test',"
        "'{\"role\":{\"production\":true}}','2026-10-17T00:00:00Z' FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    ci_plan = create_plan(
        conn,
        project="yoke",
        slug="no-target-suite",
        name="No-target suite",
        infer_target_environment=False,
    )
    replace_plan_cases(conn, plan_id=int(ci_plan["id"]), cases=[CI_CASE])
    mission_plan = create_plan(
        conn,
        project="yoke",
        slug="production-mission",
        name="Production mission",
        target_environment="prod",
    )
    replace_plan_cases(conn, plan_id=int(mission_plan["id"]), cases=[MISSION_CASE])
    insert_item(
        conn,
        id=ITEM_ID,
        title="Mixed roster",
        workflow_id="issue",
        status="implementing",
    )
    lane_path = tmp_path / BRANCH
    lane_path.mkdir()
    lane = insert_item_worktree(
        conn, item_id=ITEM_ID, branch=BRANCH, path=str(lane_path)
    )
    conn.execute(
        "UPDATE item_worktrees SET commit_sha=%s WHERE id=%s", (CANDIDATE, lane["id"])
    )
    insert_item_claim(conn, SESSION, ITEM_ID)
    for plan in (ci_plan, mission_plan):
        attach_plan_to_item(
            conn, plan_id=int(plan["id"]), item_id=ITEM_ID, transition_id=TRANSITION
        )
    materialize_for_item(conn, item_id=ITEM_ID, transition_id=TRANSITION)
    configure_test_machine(conn, tmp_path, monkeypatch)
    rows = conn.execute(
        "SELECT id, plan_case_key FROM qa_requirements WHERE item_id=%s",
        (ITEM_ID,),
    ).fetchall()
    conn.commit()
    return {str(row["plan_case_key"]): int(row["id"]) for row in rows}


def _pass(conn: Any, requirement_id: int, *, head_sha: str) -> None:
    row = conn.execute(
        "SELECT method_config, execution_target_digest FROM qa_requirements "
        "WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    raw = stamp_executed_method_config(
        canonical({"verification_tree": {"head_sha": head_sha}}),
        row["method_config"],
        execution_target_digest=str(row["execution_target_digest"]),
    )
    conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "raw_result,started_at,completed_at,created_at,case_outcome) VALUES "
        "(%s,'pytest','e2e','pass',%s,'2026-10-17T00:00:00Z',"
        "'2026-10-17T00:01:00Z','2026-10-17T00:01:00Z','passed')",
        (requirement_id, raw),
    )
    conn.commit()


def _begin(conn: Any, tmp_path: Any) -> dict[str, Any]:
    return begin_plan_execution(
        conn,
        item_id=ITEM_ID,
        transition_id=TRANSITION,
        checkout_path=str(tmp_path / BRANCH),
        expected_branch=BRANCH,
        actor_id="1",
        session_id=SESSION,
    )


def _roster_ids(execution: dict[str, Any]) -> list[int]:
    return [int(row["requirement_id"]) for row in execution["roster"]]


def test_passed_no_target_case_leaves_a_mission_only_execution(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    ids = _mixed_roster(test_db, tmp_path, monkeypatch)
    _pass(test_db, ids["full-suite"], head_sha=CANDIDATE)

    execution = _begin(test_db, tmp_path)

    assert _roster_ids(execution) == [ids["receiving-mission"]]
    assert execution["roster"][0]["ordinal"] == 0
    assert execution["remaining_requirement_count"] == 0


def test_unrun_targets_run_one_partition_and_count_the_rest(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    ids = _mixed_roster(test_db, tmp_path, monkeypatch)

    execution = _begin(test_db, tmp_path)

    assert _roster_ids(execution) == [ids["full-suite"]]
    assert execution["remaining_requirement_count"] == 1
    resumed = _begin(test_db, tmp_path)
    assert resumed["id"] == execution["id"]
    assert resumed["remaining_requirement_count"] == 1


def test_a_pass_at_another_commit_still_owes_its_case(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    ids = _mixed_roster(test_db, tmp_path, monkeypatch)
    _pass(test_db, ids["full-suite"], head_sha="b" * 40)

    execution = _begin(test_db, tmp_path)

    assert _roster_ids(execution) == [ids["full-suite"]]
    assert execution["remaining_requirement_count"] == 1


def test_every_case_passed_at_the_candidate_refuses_with_recovery(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    ids = _mixed_roster(test_db, tmp_path, monkeypatch)
    for requirement_id in ids.values():
        _pass(test_db, requirement_id, head_sha=CANDIDATE)

    with pytest.raises(
        QaPlanExecutionStateError,
        match="qa_plan_roster_passed_at_candidate.*yoke qa requirement list",
    ):
        _begin(test_db, tmp_path)
