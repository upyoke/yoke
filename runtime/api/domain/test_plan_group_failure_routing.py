"""Failed shared release plans reach only the driver, who owns triage."""

import pytest

from runtime.api.domain.test_deployment_qa_plan_group_wait_wakes import _setup
from runtime.api.domain.test_deployment_qa_plan_groups import MEMBERS, RUN, _begin
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _claim,
    seed_session,
)
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_core.domain.deployment_qa_plan_group_dispatch import (
    gate_plan_groups,
    notify_plan_group_failure,
    notify_plan_groups_wait,
)
from yoke_core.domain.deployment_qa_plan_group_failure import group_failed
from yoke_core.domain.work_claim_targets import make_steering_target


def _notices(conn):
    return conn.execute(
        "SELECT r.session_id,m.body FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id=m.message_id "
        "WHERE m.idempotency_key LIKE %s OR m.idempotency_key LIKE %s ORDER BY r.session_id",
        (f"deployment-qa-plan-group-failure:{RUN}:%", f"%{RUN}%failure-%"),
    ).fetchall()


@pytest.mark.parametrize("outcome", ["blocked", "rejected", "aborted"])
def test_failure_routes_once_per_owing_member_after_a_wait_notice(test_db, outcome):
    group = _setup(test_db, manual=False)
    # A carried member's fallback must use its own project, not the run's.
    test_db.execute("UPDATE items SET project_id=2 WHERE id=%s", (MEMBERS[-1],))
    seed_session(test_db, "member-steering")
    _claim(
        test_db,
        session_id="member-steering",
        target_kind="steering",
        scope_json=make_steering_target(2).scope_json(),
    )
    test_db.commit()
    notify_plan_groups_wait(
        test_db,
        run_id=RUN,
        stage_name="item-qa",
        groups=[group],
        project_id=1,
        item_refs=str,
    )
    if outcome == "aborted":
        execution = _begin(test_db)
        test_db.execute(
            "UPDATE qa_plan_executions SET state='aborted' WHERE id=%s",
            (execution["id"],),
        )
        test_db.commit()
    assert group_failed(test_db, group, {"outcome": outcome})
    for _ in range(2):
        notify_plan_group_failure(
            test_db,
            run_id=RUN,
            stage_name="item-qa",
            group=group,
            project_id=1,
            reasons=[outcome],
            item_refs=str,
        )
    notices = _notices(test_db)
    assert [row[0] for row in notices] == [DRIVER_SESSION]
    body = notices[0][1]
    assert all(str(member) in body for member in MEMBERS)
    assert "driver owns triage" in body
    source = test_db.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id=%s", (RUN,)
    ).fetchone()[0]
    assert source in body
    assert "Retry reruns on that commit" in body
    assert "later commit" in body and f"takes over {RUN}" in body
    for command in (
        "lifecycle transition",
        "qa plan run",
        "qa requirement waive",
        "deployment-runs remove-item",
    ):
        assert command in body


def test_aborted_attempt_with_a_live_retry_sends_nothing(test_db):
    group = _setup(test_db, manual=False)
    execution = _begin(test_db)
    test_db.execute(
        "UPDATE qa_plan_executions SET state='aborted' WHERE id=%s", (execution["id"],)
    )
    test_db.commit()
    _begin(test_db)
    assert not group_failed(test_db, group, {"outcome": "waiting"})
    gate_plan_groups(
        test_db,
        {"scope": "item", "name": "item-qa"},
        run_id=RUN,
        project_id=1,
        item_refs=str,
    )
    assert _notices(test_db) == []


def test_dispatch_and_settlement_route_resultless_abort(test_db):
    from yoke_core.domain.deployment_qa_plan_group_writes import group_subject
    from yoke_core.domain.deployment_qa_stage_settlement import settle_plan_group

    group = _setup(test_db, manual=False)
    execution = _begin(test_db)
    test_db.execute(
        "UPDATE qa_plan_executions SET state='aborted' WHERE id=%s", (execution["id"],)
    )
    test_db.commit()
    gate_plan_groups(
        test_db,
        {"scope": "item", "name": "item-qa"},
        run_id=RUN,
        project_id=1,
        item_refs=str,
    )
    assert len(_notices(test_db)) == 1
    before = list(_notices(test_db))
    subject = group_subject(test_db, RUN, "item-qa", group, require_active=True)
    settle_plan_group(test_db, subject)
    assert len(_notices(test_db)) == len(before)


@pytest.mark.parametrize("batch", [True, False])
def test_failed_group_notices_survive_member_acceptance_and_repeat_dispatch(
    test_db, batch
):
    from yoke_core.domain.deployment_qa_member_acceptance_notice import (
        notify_item_qa_accepted,
    )
    from yoke_core.domain.deployment_qa_stage_dispatch import (
        materialize_and_gate_deployment_qa_stage,
    )

    _setup(test_db, manual=False)
    execution = _begin(test_db)
    test_db.execute(
        "UPDATE qa_plan_executions SET state='aborted' WHERE id=%s", (execution["id"],)
    )
    test_db.commit()

    def dispatch():
        rc, _ = materialize_and_gate_deployment_qa_stage(
            test_db,
            {"scope": "item", "name": "item-qa"},
            run_id=RUN,
        )
        assert rc != 0
        if not batch:
            for member in MEMBERS:
                notify_item_qa_accepted(test_db, run_id=RUN, item_id=member)
        test_db.commit()
        rows = test_db.execute(
            "SELECT message_id,cancelled_at FROM session_messages "
            "WHERE idempotency_key LIKE %s ORDER BY message_id",
            (f"deployment-qa-plan-group-failure:{RUN}:%",),
        ).fetchall()
        return [(row[0], row[1]) for row in rows]

    first = dispatch()
    assert len(first) == 1
    assert all(row[1] is None for row in first)
    assert dispatch() == first


@pytest.mark.parametrize("outcome", ["aborted", "failed"])
def test_failed_group_fleet_recovery_names_pinned_commit(test_db, outcome):
    from yoke_core.domain.deployment_qa_plan_group_standings import group_blockers

    _setup(test_db, manual=False)
    execution = _begin(test_db)
    if outcome == "failed":
        from runtime.api.domain.test_deployment_qa_plan_group_execution import (
            _fail_case,
        )

        _fail_case(test_db, execution)
    else:
        test_db.execute(
            "UPDATE qa_plan_executions SET state='aborted' WHERE id=%s",
            (execution["id"],),
        )
        test_db.commit()
    recovery = " ".join(
        reason
        for _, _, reasons in group_blockers(test_db, RUN, "item-qa")
        for reason in reasons
    )
    source = test_db.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id=%s", (RUN,)
    ).fetchone()[0]
    assert source in recovery
    assert "Retry reruns on that commit" in recovery
    assert "later commit" in recovery and f"takes over {RUN}" in recovery
    assert "Waive discharges" in recovery and "remove detaches" in recovery
