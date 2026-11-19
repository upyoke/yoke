"""Plan groups moved across release takeovers whose successors each deployed."""

from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    MEMBERS,
    RUN,
    SLUG,
    _seed,
)
from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_run_qa_transfer import transfer_qa_on
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_execution_store import select_plan_execution

SESSION = "plan-group-qa"
FIRST = "run-plan-groups-first-successor"
SECOND = "run-plan-groups-second-successor"
LINEAGES = {RUN: "a" * 40, FIRST: "d" * 40, SECOND: "e" * 40}


def seed_open_group(conn, *, cases: int = 1) -> int:
    """RUN deployed and formed one open group of the smoke plan."""
    plan_id = _seed(conn)
    if cases > 1:
        from yoke_core.domain.qa_plan_management import replace_plan_cases

        replace_plan_cases(
            conn,
            plan_id=plan_id,
            cases=[
                {
                    "case_key": f"command-smoke-{position}",
                    "position": position,
                    "method_id": "command",
                    "instructions": "run the frozen smoke command",
                    "expected_outcome": "the command passes",
                    "method_config": {"command": "true"},
                    "target_envs": [],
                }
                for position in range(1, cases + 1)
            ],
        )
    ensure_groups(conn, RUN, "item-qa")
    conn.commit()
    return plan_id


def take_over(conn, plan_id: int, old: str, new: str) -> None:
    """``new`` supersedes ``old`` with every member and has deployed its own build."""
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(
        conn,
        run_id=new,
        stages=stages,
        members=(),
        existing_members=MEMBERS,
        release_lineage=LINEAGES[new],
    )
    conn.execute(
        "UPDATE deployment_runs SET supersedes_run_id=%s WHERE id=%s", (old, new)
    )
    transfer_qa_on(conn, old_id=old, new_id=new, moving=set(MEMBERS))
    conn.execute("DELETE FROM deployment_run_items WHERE run_id=%s", (old,))
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=ANY(%s)",
        (f"flow-{new}", list(MEMBERS)),
    )
    conn.commit()


def begin_group(conn, run_id: str) -> dict:
    return begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        plan=SLUG,
        actor_id="2",
        session_id=SESSION,
    )


def wait_for_host(conn, execution: dict) -> None:
    """The host-turn wait: a check-in pause at cursor zero."""
    from yoke_core.domain.qa_plan_execution_reentry import PAUSE_REASON

    evidence = json.dumps(
        {"phase": "checkin", "cursor": 0, "request_id": "host-turn", "attempts": []}
    )
    conn.execute(
        "UPDATE qa_plan_executions SET state='waiting',release_reason=%s WHERE id=%s",
        (PAUSE_REASON + evidence, execution["id"]),
    )
    conn.commit()


def resume(conn, execution_id: str) -> dict | None:
    """The server's resume re-freeze, as ``--resume-execution-id`` reaches it."""
    from yoke_core.domain.deployment_qa_execution_refreeze import (
        resume_moved_execution,
    )

    execution = select_plan_execution(conn, execution_id, lock=False)
    parsed = SimpleNamespace(checkout_path=None, expected_branch=None, test_machine=None)
    actor = SimpleNamespace(actor_id="2", session_id=SESSION)
    return resume_moved_execution(conn, execution, parsed, actor)


def order(conn, execution_id: str) -> int:
    return conn.execute(
        "SELECT execution_order FROM qa_plan_executions WHERE id=%s", (execution_id,)
    ).fetchone()["execution_order"]


def row_targets(conn, run_id: str) -> list[dict]:
    (group,) = run_groups(conn, [run_id], "item-qa")
    rows = conn.execute(
        "SELECT execution_target_json FROM qa_requirements WHERE id=ANY(%s) ORDER BY id",
        (list(group.requirement_ids),),
    ).fetchall()
    return [json.loads(row["execution_target_json"]) for row in rows]


def pass_first_case(conn, execution: dict) -> int:
    """Record a pass for the walk's first case, then stop the walk there."""
    from yoke_core.domain.qa_plan_execution_state import (
        advance_plan_execution,
        finish_plan_execution,
    )
    from yoke_core.domain.qa_requirement_pass_currency import (
        stamp_executed_method_config,
    )

    requirement_id = int(execution["roster"][0]["requirement_id"])
    now = "2026-09-14T00:02:00Z"
    config = conn.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()[0]
    raw = stamp_executed_method_config(
        "group case passed", config, conn=conn, requirement_id=requirement_id
    )
    run_id = conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "raw_result,started_at,completed_at,created_at) VALUES "
        "(%s,'worktree_run','plan_case','pass',%s,%s,%s,%s) RETURNING id",
        (requirement_id, raw, now, now, now),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,created_at) VALUES (%s,'log','application/json',%s,%s)",
        (run_id, "evidence://group-case", now),
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
            "run_id": int(run_id),
        },
    )
    finish_plan_execution(conn, execution, state="aborted", reason="test-stop")
    conn.commit()
    return requirement_id
