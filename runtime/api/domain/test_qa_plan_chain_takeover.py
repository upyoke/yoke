"""A chained plan run keeps its chain across a release takeover.

Takeover moves the plan run and its requirements to the successor run, while
the frozen roster keeps the run that admitted each case. The chain's
predecessor lookup once filtered on that frozen run, found nothing, and
blocked every inheriting case with "requirement None did not run directly
before it" (feedback 97486).
"""

from __future__ import annotations

from runtime.api.domain.machine_qa_session_seed import seed_registered_qa_launch
from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_case_chain import inherit_blocker
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
from yoke_core.domain.qa_plan_execution_state import advance_plan_execution
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

MEMBER = takeover.WAITING


def _chained_plan(conn) -> int:
    plan = create_plan(
        conn,
        project="yoke",
        slug="chain-takeover",
        name="chain-takeover",
        infer_target_environment=False,
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": key,
                "method_id": "terminal-check",
                "instructions": "Check the terminal",
                "expected_outcome": "Done",
                "entry_surface": "/usr/bin/true",
                "required_completion": "done",
                **start,
                "method_config": {
                    "os": "macos",
                    "steps": [{"key": "done", "expect": "done"}],
                },
            }
            for key, start in (
                ("install", {"host_baselines": ["fresh-host"]}),
                ("add-local", {"starting_state": "inherit"}),
            )
        ],
    )
    return int(plan["id"])


def _execution_past_its_first_case(conn, tmp_path, monkeypatch) -> dict:
    """OLD runs a two-case chain for MEMBER and its first case has captured."""
    configure_test_machine(conn, tmp_path, monkeypatch)
    stages = item_qa_stage_definitions(_chained_plan(conn))
    stages[1]["cases"]["case_keys"] = ["install", "add-local"]
    seed_run_standing_on_qa_stage(
        conn,
        run_id=takeover.OLD,
        project="yoke",
        stages=stages,
        members=(MEMBER,),
        lineage=takeover.OLD_LINEAGE,
    )
    conn.execute(
        "UPDATE items SET status='release',deployment_flow=%s WHERE id=%s",
        (f"flow-{takeover.OLD}", MEMBER),
    )
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=takeover.OLD,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
    )
    conn.commit()
    seed_registered_qa_launch(conn, takeover.DRIVER_SESSION)
    execution = begin_plan_execution(
        conn,
        deployment_run_id=takeover.OLD,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        actor_id="1",
        session_id=takeover.DRIVER_SESSION,
    )
    first = execution["roster"][0]
    advance_plan_execution(
        conn,
        lock_plan_execution(conn, execution["id"]),
        ordinal=0,
        requirement_id=int(first["requirement_id"]),
        result={
            "requirement_id": int(first["requirement_id"]),
            "plan_id": first["plan_id"],
            "case_key": first["case_key"],
            "case_position": first["case_position"],
            "baseline_position": first["baseline_position"],
            "host_baseline": "fresh-host",
            "case_outcome": "passed",
            "verdict": "pass",
        },
        commit=True,
    )
    return execution


def test_second_case_links_to_its_predecessor_after_a_takeover(
    test_db, tmp_path, monkeypatch
):
    execution = _execution_past_its_first_case(test_db, tmp_path, monkeypatch)
    takeover._seed_new(test_db)
    takeover._contains(monkeypatch)
    assert takeover._take_over(test_db) == takeover.OLD

    moved = lock_plan_execution(test_db, execution["id"])
    second = moved["roster"][1]
    assert moved["deployment_run_id"] == takeover.NEW
    assert second["deployment_run_id"] == takeover.OLD
    assert [case["case_key"] for case in moved["roster"]] == ["install", "add-local"]

    assert inherit_blocker(test_db, moved, second, ordinal=1) is None


def test_an_unproven_move_names_the_run_instead_of_requirement_none(
    test_db, tmp_path, monkeypatch
):
    execution = _execution_past_its_first_case(test_db, tmp_path, monkeypatch)
    takeover._seed_new(test_db)
    takeover._contains(monkeypatch)
    assert takeover._take_over(test_db) == takeover.OLD
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_takeover_identity.inherited_target",
        lambda *_args: False,
    )

    moved = lock_plan_execution(test_db, execution["id"])
    blocker = inherit_blocker(test_db, moved, moved["roster"][1], ordinal=1)

    assert blocker is not None
    assert blocker["predecessor_requirement_id"] is None
    assert "None" not in blocker["reason"]
    assert takeover.NEW in blocker["reason"] and takeover.OLD in blocker["reason"]
    assert "no takeover links" in blocker["reason"]


def test_a_missing_predecessor_row_is_named(test_db, tmp_path, monkeypatch):
    execution = _execution_past_its_first_case(test_db, tmp_path, monkeypatch)
    first = int(execution["roster"][0]["requirement_id"])
    test_db.execute("UPDATE qa_requirements SET plan_id=NULL WHERE id=%s", (first,))
    test_db.commit()

    moved = lock_plan_execution(test_db, execution["id"])
    blocker = inherit_blocker(test_db, moved, moved["roster"][1], ordinal=1)

    assert blocker is not None
    assert "None" not in blocker["reason"]
    assert "no requirement for that earlier plan case exists" in blocker["reason"]
