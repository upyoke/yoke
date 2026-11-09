"""Passed or waived member QA closes on delivery without another wake."""

from __future__ import annotations

from runtime.api.domain.satisfied_delivery_member_close_out_test_support import (
    _settled_member_requirement as _settled_member_requirement,
    _waived_item_requirement as _waived_item_requirement,
)


from typing import Any

import pytest

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _parked_owner,
    _project,
    _run,
)
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    _bodies,
    _recipients,
)
from runtime.api.domain.no_obligation_member_close_out_test_support import (
    _no_obligation,
    _ready_member,
)
from runtime.api.domain.run_success_member_settlement_test_support import _executing_run
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_delivery_close_out_notice import (
    delivery_cleared_idempotency_key,
    notify_delivery_cleared,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.no_obligation_member_close_out import satisfied_delivery_member


SATISFIED_QA_ITEM = 9827


def test_satisfied_member_qa_still_refuses_an_unsatisfied_closure_dependency(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, SATISFIED_QA_ITEM, HOLDER_A)
    blocker = SATISFIED_QA_ITEM + 1
    insert_item(test_db, id=blocker, project_sequence=blocker, status="release")
    test_db.execute(
        "INSERT INTO item_dependencies(dependent_item_id,blocking_item_id,"
        "gate_point,satisfaction,source,created_at) "
        "VALUES(%s,%s,'closure','status:done','operator','2026-10-01T00:00:00Z')",
        (SATISFIED_QA_ITEM, blocker),
    )
    run_id = "run-closure-refusal"
    _run(test_db, run_id, flow=COMPLETION_FLOW, members=(SATISFIED_QA_ITEM,))
    _settled_member_requirement(
        test_db, item_id=SATISFIED_QA_ITEM, run_id=run_id, resolution="pass"
    )

    [report] = notify_delivery_cleared(test_db, run_id=run_id)

    assert report["delivery"].startswith("failed:")
    assert "closure dependency(ies) remain unsatisfied" in report["delivery"]
    assert (
        test_db.execute(
            "SELECT status FROM items WHERE id=%s", (SATISFIED_QA_ITEM,)
        ).fetchone()["status"]
        == "release"
    )


def test_waived_item_check_does_not_hold_collective_finalization(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, SATISFIED_QA_ITEM, HOLDER_A)
    _waived_item_requirement(test_db, SATISFIED_QA_ITEM)
    run_id = "run-waived-intake-settlement"
    _executing_run(test_db, run_id, (SATISFIED_QA_ITEM,))
    assert (
        test_db.execute(
            "SELECT COUNT(*) AS count FROM qa_requirements WHERE deployment_run_id=%s",
            (run_id,),
        ).fetchone()["count"]
        == 0
    )

    assert cmd_update(run_id, "status", "succeeded") is None

    assert (
        test_db.execute(
            "SELECT status FROM items WHERE id=%s", (SATISFIED_QA_ITEM,)
        ).fetchone()["status"]
        == "done"
    )
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()["status"]
        == "succeeded"
    )


@pytest.mark.parametrize("answer", ["unanswered", "no_obligation", "waived"])
def test_unsettled_run_requirement_holds_every_item_answer(test_db: Any, answer: str):
    _project(test_db)
    _member_at_release_wait(test_db, SATISFIED_QA_ITEM)
    if answer == "waived":
        _waived_item_requirement(test_db, SATISFIED_QA_ITEM)
    elif answer == "no_obligation":
        _no_obligation(test_db, SATISFIED_QA_ITEM, reason="no observable change")
    run_id = f"run-unsettled-{answer}"
    _run(test_db, run_id, flow=COMPLETION_FLOW, members=(SATISFIED_QA_ITEM,))
    insert_qa_requirement(
        test_db,
        item_id=None,
        deployment_run_id=run_id,
        deployment_member_item_id=SATISFIED_QA_ITEM,
        deployment_stage="item-qa",
        qa_kind="plan_case",
        qa_phase="post_deploy",
        blocking_mode="blocking",
    )

    assert not satisfied_delivery_member(
        test_db, item_id=SATISFIED_QA_ITEM, run_id=run_id
    )


@pytest.mark.parametrize("resolution", ["pass", "waive"])
def test_satisfied_member_qa_closes_without_a_delivery_wake(
    test_db: Any, monkeypatch, resolution: str
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, SATISFIED_QA_ITEM, HOLDER_A)
    run_id = f"run-satisfied-{resolution}"
    _run(
        test_db,
        run_id,
        flow=COMPLETION_FLOW,
        members=(SATISFIED_QA_ITEM,),
    )
    _settled_member_requirement(
        test_db,
        item_id=SATISFIED_QA_ITEM,
        run_id=run_id,
        resolution=resolution,
    )

    [report] = notify_delivery_cleared(test_db, run_id=run_id)

    assert report["delivery"] == "closed"
    key = delivery_cleared_idempotency_key(SATISFIED_QA_ITEM, run_id)
    assert _recipients(test_db, key) == []
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s", (SATISFIED_QA_ITEM,)
    ).fetchone()["status"]
    assert status == "done"
    holder = test_db.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id=%s", (HOLDER_A,)
    ).fetchone()
    assert holder is not None and holder["ended_at"] is not None


def test_satisfied_member_close_out_refusal_sends_recovery_notice(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _member_at_release_wait(test_db, SATISFIED_QA_ITEM)
    _parked_owner(test_db, HOLDER_A, SATISFIED_QA_ITEM)
    run_id = "run-satisfied-refusal"
    _run(
        test_db,
        run_id,
        flow=COMPLETION_FLOW,
        members=(SATISFIED_QA_ITEM,),
    )
    _settled_member_requirement(
        test_db,
        item_id=SATISFIED_QA_ITEM,
        run_id=run_id,
        resolution="pass",
    )

    [report] = notify_delivery_cleared(test_db, run_id=run_id)

    assert report["delivery"].startswith("failed:")
    assert "execution_evidence" in report["delivery"]
    assert "recovery notice" in report["delivery"]
    key = delivery_cleared_idempotency_key(SATISFIED_QA_ITEM, run_id)
    assert _recipients(test_db, key) == [HOLDER_A]
    [body] = _bodies(test_db, key)
    assert "Automatic close-out failed" in body
    assert "execution_evidence" in body
    assert "yoke merge item" in body
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s", (SATISFIED_QA_ITEM,)
    ).fetchone()["status"]
    assert status != "done"
    run_status = test_db.execute(
        "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()["status"]
    assert run_status == "succeeded"


def _settle_group(conn, run_id):
    from yoke_core.domain.deployment_qa_plan_group_dispatch import settle_group
    from yoke_core.domain.deployment_qa_plan_group_writes import group_subject
    from yoke_core.domain.deployment_qa_plan_groups import run_groups

    for group in run_groups(conn, [run_id], "item-qa"):
        if group.open:
            settle_group(
                conn,
                group_subject(conn, run_id, "item-qa", group, require_active=False),
            )
    conn.commit()


@pytest.mark.parametrize("resolution", ["pending", "pass", "fail", "waive"])
def test_member_with_only_plan_group_checks_settles_after_resolution(
    test_db, resolution
):
    from runtime.api.domain.deployment_qa_plan_group_execution_test_support import (
        _fail_case,
    )
    from runtime.api.domain.deployment_qa_plan_groups_test_support import (
        MEMBERS,
        RUN,
        _begin,
        _seed,
    )
    from runtime.api.domain.deployment_qa_stage_execution_test_support import (
        _complete_case,
    )
    from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

    _seed(test_db)
    (requirement_id,) = ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    if resolution == "pass":
        _complete_case(test_db, _begin(test_db))
    elif resolution == "fail":
        _fail_case(test_db, _begin(test_db))
    elif resolution == "waive":
        from yoke_core.domain.qa_requirement_ops import waive_requirement

        waive_requirement(
            test_db, requirement_id, "accepted", source="operator", force=True
        )
    _settle_group(test_db, RUN)
    for member in MEMBERS:
        assert satisfied_delivery_member(test_db, item_id=member, run_id=RUN) is (
            resolution in {"pass", "waive"}
        )


def test_another_plan_s_open_group_does_not_hold_a_member_it_does_not_answer(test_db):
    from runtime.api.domain.deployment_qa_plan_groups_test_support import (
        MEMBERS,
        RUN,
        _attach,
        _pass_group,
        _seed,
    )
    from runtime.api.domain.deployment_qa_stage_execution_test_support import _plan
    from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

    _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _pass_group(test_db)
    other_plan = _plan(test_db, "other-settlement-plan")
    _attach(test_db, MEMBERS[1], other_plan)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    assert satisfied_delivery_member(test_db, item_id=MEMBERS[0], run_id=RUN)
    assert not satisfied_delivery_member(test_db, item_id=MEMBERS[1], run_id=RUN)
