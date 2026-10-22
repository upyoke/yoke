"""A shared stage roster's machine groups run concurrently, one per session."""

from __future__ import annotations

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    _terminal_recipe,
    configure_test_machine,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _attach,
    _materialize,
)
from runtime.api.domain.test_deployment_qa_shared_wait import _holders, _notices
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    SESSION_ACTOR_ID,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import select_plan_execution
from yoke_core.domain.qa_plan_host_leases import execution_host_leases
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

MAC, STUDIO = "mac-mini-lab", "mac-studio-lab"
SESSIONS = ("partition-a", "partition-b", "partition-c")


def _case(key, driver, *, machines=None, inherit=False):
    return {
        "case_key": key,
        "method_id": "terminal-check",
        "instructions": "Run a host-specific check.",
        "expected_outcome": "The check passes.",
        "method_config": {
            **_terminal_recipe(),
            "machine": driver,
            **({"machines": list(machines)} if machines else {}),
        },
        "entry_surface": "printf done",
        "required_completion": "complete",
        "starting_state": "inherit" if inherit else "as_is",
        "starting_state_reason": None
        if inherit
        else "The check reads host identity only and needs no reset.",
    }


def _seed(conn, tmp_path, monkeypatch, cases, *, separate_plans=True):
    configure_test_machine(conn, tmp_path, monkeypatch)
    replace_test_machine_settings(
        conn,
        project="yoke",
        machine=STUDIO,
        settings={**TEST_MACHINE_SETTINGS, "resource_name": STUDIO},
        base_settings=None,
    )
    seed_qa_session(conn, *SESSIONS)
    groups = []
    for case in cases:
        if not groups or (separate_plans and case["starting_state"] != "inherit"):
            groups.append([])
        groups[-1].append(case)
    plans = []
    for index, group in enumerate(groups):
        plan = create_plan(
            conn,
            project="yoke",
            slug=f"shared-hosts-{index}",
            infer_target_environment=False,
        )
        replace_plan_cases(
            conn,
            plan_id=int(plan["id"]),
            cases=[{**case, "position": i} for i, case in enumerate(group, 1)],
        )
        plans.append(int(plan["id"]))
    stages = _stages(plans[0])
    stages[1].pop("cases")
    _seed_run(conn, run_id=RUN, stages=stages, members=MEMBERS)
    for member in MEMBERS:
        for plan_id in plans:
            _attach(conn, member, plan_id)
        _materialize(conn, member)


def _begin(conn, session, member=MEMBERS[0], actor="1"):
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id=actor,
        session_id=session,
    )


def _keys(execution):
    return [case["case_key"] for case in execution["roster"]]


def _case_begin(execution, session):
    return handle_plan_case_begin(
        FunctionCallRequest(
            function="test_machine.plan_case.begin",
            actor=ActorContext(actor_id="1", session_id=session),
            target=TargetRef(kind="global", project_id="yoke"),
            payload={
                "execution_id": execution["id"],
                "ordinal": 0,
                "requirement_id": execution["roster"][0]["requirement_id"],
            },
        )
    )


TWO_HOSTS = [_case("on-mac", MAC), _case("on-studio", STUDIO)]


def test_two_sessions_walk_disjoint_groups_and_hold_leases_together(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, TWO_HOSTS)
    first = _begin(test_db, SESSIONS[0])
    second = _begin(test_db, SESSIONS[1], MEMBERS[1])
    assert (_keys(first), _keys(second)) == (["on-mac"], ["on-studio"])
    assert first["state"] == second["state"] == "active"
    leases = []
    for execution, session in ((first, SESSIONS[0]), (second, SESSIONS[1])):
        response = _case_begin(execution, session)
        assert response.primary_success, response.error
        assert response.result_payload["state"] == "ready"
        leases.append(response.result_payload["execution"]["lease_id"])
    held = test_db.execute(
        "SELECT COUNT(*) FROM work_claims WHERE id = ANY(%s) AND released_at IS NULL",
        (leases,),
    ).fetchone()[0]
    assert held == 2
    # Each session resumes its own row, not the stage's newest one.
    assert _begin(test_db, SESSIONS[0])["id"] == first["id"]
    assert _begin(test_db, SESSIONS[1], MEMBERS[1])["id"] == second["id"]


def test_third_session_waits_only_when_every_group_is_held(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, TWO_HOSTS)
    first = _begin(test_db, SESSIONS[0])
    second = _begin(test_db, SESSIONS[1], MEMBERS[1])
    waiting = _begin(test_db, SESSIONS[2])
    assert waiting["state"] == "waiting"
    assert waiting["shared_execution_wait"]["execution_id"] in {
        first["id"],
        second["id"],
    }
    assert "park" in waiting["recovery"]


def test_abandoned_partition_is_aborted_and_its_group_reoffered(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, TWO_HOSTS)
    first = _begin(test_db, SESSIONS[0])
    _begin(test_db, SESSIONS[1], MEMBERS[1])
    test_db.execute(
        "UPDATE qa_plan_executions SET heartbeat_at='2026-01-01T00:00:00Z' WHERE id=%s",
        (first["id"],),
    )
    test_db.commit()
    third = _begin(test_db, SESSIONS[2])
    assert _keys(third) == _keys(first)
    assert third["session_id"] == SESSIONS[2]
    assert select_plan_execution(test_db, first["id"], lock=False)["state"] == "aborted"


def test_inherit_chain_stays_in_one_group(test_db, tmp_path, monkeypatch):
    _seed(
        test_db,
        tmp_path,
        monkeypatch,
        [
            _case("opener", MAC),
            _case("follower", MAC, inherit=True),
            _case("on-studio", STUDIO),
        ],
    )
    first = _begin(test_db, SESSIONS[0])
    second = _begin(test_db, SESSIONS[1], MEMBERS[1])
    assert _keys(first) == ["opener", "follower"]
    assert _keys(second) == ["on-studio"]


def test_overlapping_host_sets_never_deadlock(test_db, tmp_path, monkeypatch):
    both = (MAC, STUDIO)
    _seed(
        test_db,
        tmp_path,
        monkeypatch,
        [
            _case("drives-mac", MAC, machines=both),
            _case("drives-studio", STUDIO, machines=both),
        ],
    )
    first = _begin(test_db, SESSIONS[0])
    second = _begin(test_db, SESSIONS[1], MEMBERS[1])
    assert {_keys(first)[0], _keys(second)[0]} == {"drives-mac", "drives-studio"}
    ready = _case_begin(first, SESSIONS[0])
    assert ready.primary_success, ready.error
    assert ready.result_payload["state"] == "ready"
    blocked = _case_begin(second, SESSIONS[1])
    assert blocked.primary_success, blocked.error
    assert blocked.result_payload["state"] == "waiting"
    # The waiting group holds neither host, so no hold-and-wait cycle forms.
    held = execution_host_leases(test_db, lock_plan_execution(test_db, second["id"]))
    assert (
        held == []
        and lock_plan_execution(test_db, second["id"])["machine_lease_id"] is None
    )
    test_db.commit()


def test_stage_settles_after_every_partition_and_wakes_each_time(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, TWO_HOSTS)
    _holders(test_db)
    actor = str(SESSION_ACTOR_ID)
    first = _begin(test_db, "member-9901", actor=actor)
    second = _begin(test_db, "member-9902", MEMBERS[1], actor=actor)
    _complete_case(test_db, lock_plan_execution(test_db, first["id"]))
    for member in MEMBERS:
        assert not deployment_qa_stage_status(
            test_db, run_id=RUN, stage_name="item-qa", member_item_id=member
        )["accepted"]
    assert {row["session_id"] for row in _notices(test_db, first)} == {
        "member-9901",
        "member-9902",
    }
    _complete_case(test_db, lock_plan_execution(test_db, second["id"]))
    for member in MEMBERS:
        assert deployment_qa_stage_status(
            test_db, run_id=RUN, stage_name="item-qa", member_item_id=member
        )["accepted"]


def test_same_session_insert_race_converges_on_its_own_row(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, TWO_HOSTS)
    first = _begin(test_db, SESSIONS[0])
    # The lookup before the insert misses the row a concurrent begin wrote.
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_begin.live_plan_execution_id",
        lambda *_args, **_kwargs: None,
    )
    assert _begin(test_db, SESSIONS[0])["id"] == first["id"]
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_plan_executions WHERE session_id=%s",
            (SESSIONS[0],),
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("member", [None, MEMBERS[0]])
def test_lookup_of_a_stage_wide_execution_needs_its_session(test_db, member):
    from yoke_core.domain.qa_plan_execution_store import (
        QaPlanExecutionStateError,
        live_plan_execution_id,
    )

    scope = dict(
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )
    if member is None:
        with pytest.raises(QaPlanExecutionStateError, match="needs a session"):
            live_plan_execution_id(test_db, **scope)
    else:
        assert live_plan_execution_id(test_db, **scope) is None
