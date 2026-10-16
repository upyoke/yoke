"""A run settles on its own target; holding is per target environment."""

import json
import pytest

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _bodies,
    _claim,
    seed_session,
)
from runtime.api.domain.test_dash_post_deploy_done_consumption import (
    _accept_member_qa,
)
from runtime.api.domain.test_post_deploy_original_pass_needs_admission import (
    _record_evidence,
)
from runtime.api.domain.test_release_member_target_enrollment import _pair
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog_inserts import insert_qa_run
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from yoke_core.domain.actor_permissions import (
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    notify_item_qa_accepted,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_collective_finalization import (
    _split_waiting_members,
    mark_settling,
    settle_members,
)
from yoke_core.domain.deployment_run_member_targeting import (
    holder_covers_run,
    run_needs_member,
)
from yoke_core.domain.deployment_run_other_target_members import (
    SET_ASIDE_KEY_PREFIX,
    owes_only_other_targets,
)


def _item(conn, item_id):
    return conn.execute(
        "SELECT status,deployed_to FROM items WHERE id=%s", (item_id,)
    ).fetchone()


def _executing(conn, run_id):
    conn.execute("UPDATE deployment_runs SET status='executing' WHERE id=%s", (run_id,))
    conn.commit()


def _production_delivered(conn, item_id):
    """Production answered its own obligation; the stage one is still owed."""
    sources = _pair(conn, item_id=item_id)
    _record_evidence(conn, item_id=item_id)
    _executing(conn, "run-stage")
    _accept_member_qa(conn, run_id="run-prod", item_id=item_id)
    _executing(conn, "run-prod")
    return sources


def test_production_holder_without_a_selection_does_not_hold_stage_obligations(
    test_db,
):
    item_id = 9750
    _pair(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=NULL,"
        "requirement_selection=NULL WHERE run_id='run-prod'"
    )
    test_db.commit()

    assert run_needs_member(test_db, run_id="run-stage", item_id=item_id)
    assert not holder_covers_run(
        test_db, holder_id="run-prod", run_id="run-stage", item_id=item_id
    )


def test_production_selection_naming_stage_cases_does_not_hold_them(test_db):
    item_id = 9751
    sources = _pair(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=NULL,"
        "requirement_selection=%s WHERE run_id='run-prod'",
        (
            json.dumps(
                {
                    "schema": 1,
                    "requirement_ids": [sources["stage"], sources["prod"]],
                    "plan_ids": [],
                }
            ),
        ),
    )
    test_db.commit()

    assert not holder_covers_run(
        test_db, holder_id="run-prod", run_id="run-stage", item_id=item_id
    )


def test_production_run_settles_while_a_member_still_owes_stage(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    item_id = 9752
    _production_delivered(test_db, item_id)

    assert owes_only_other_targets(test_db, run_id="run-prod", item_id=item_id)
    required, deferred = _split_waiting_members(test_db, "run-prod")
    assert [member["item_id"] for member in deferred] == [item_id]
    assert required == []

    mark_settling(test_db, "run-prod")
    assert settle_members(test_db, "run-prod") is None
    row = _item(test_db, item_id)
    assert row["status"] == "release"
    assert row["deployed_to"] == "prod"


def test_set_aside_member_holder_gets_one_notice_naming_what_it_owes(
    test_db, monkeypatch
):
    """Nothing else drives the remaining acceptance, so its owner is told once."""
    _isolate_status_effects(monkeypatch)
    item_id = 9757
    sources = _production_delivered(test_db, item_id)
    seed_roles_and_permissions(test_db)
    grant_actor_project_role(test_db, actor_id=1, project_id=1, role_name="owner")
    seed_session(test_db, "set-aside-holder", project_id=1)
    _claim(
        test_db,
        session_id="set-aside-holder",
        target_kind="item",
        scope_json=json.dumps({"item_id": item_id}),
    )

    mark_settling(test_db, "run-prod")
    assert settle_members(test_db, "run-prod") is None
    assert settle_members(test_db, "run-prod") is None

    bodies = _bodies(test_db, f"{SET_ASIDE_KEY_PREFIX}{item_id}:run-prod")
    assert len(bodies) == 1
    assert f"requirement {sources['stage']}" in bodies[0]
    assert "on stage" in bodies[0]
    assert "delivered to prod" in bodies[0]
    assert "yoke qa plan run --deployment-run-id" in bodies[0]
    assert "You hold its work claim" in bodies[0]
    assert f"requirement {sources['prod']}" not in bodies[0]


def test_own_target_red_still_blocks_settlement(test_db):
    item_id = 9753
    _pair(test_db, item_id=item_id)
    _record_evidence(test_db, item_id=item_id)
    admitted = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-prod",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    insert_qa_run(
        test_db,
        qa_requirement_id=admitted["created_requirement_ids"][0],
        verdict="fail",
    )
    _executing(test_db, "run-prod")

    assert not owes_only_other_targets(test_db, run_id="run-prod", item_id=item_id)
    required, deferred = _split_waiting_members(test_db, "run-prod")
    assert [member["item_id"] for member in required] == [item_id]
    assert deferred == []
    mark_settling(test_db, "run-prod")
    refusal = settle_members(test_db, "run-prod")
    assert refusal is not None and "have not settled" in refusal
    assert _item(test_db, item_id)["status"] == "release"


def test_member_closes_when_its_stage_obligation_passes(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    item_id = 9754
    _production_delivered(test_db, item_id)
    mark_settling(test_db, "run-prod")
    assert settle_members(test_db, "run-prod") is None
    test_db.execute("UPDATE deployment_runs SET status='succeeded' WHERE id='run-prod'")
    test_db.commit()
    assert _item(test_db, item_id)["status"] == "release"

    _accept_member_qa(test_db, run_id="run-stage", item_id=item_id)
    closed = notify_item_qa_accepted(test_db, run_id="run-stage", item_id=item_id)

    assert closed == "closed"
    assert _item(test_db, item_id)["status"] == "done"


def test_auto_completion_does_not_wait_on_another_targets_obligation(
    test_db, monkeypatch
):
    from yoke_core.domain.deployment_run_auto_completion import _readiness

    item_id = 9755
    _production_delivered(test_db, item_id)
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='member-qa' WHERE id='run-prod'"
    )
    test_db.commit()
    release_seeded_driver(test_db, "run-prod")

    ready, reason = _readiness(test_db, "run-prod")

    assert ready is not None, reason
    assert item_id in ready["members"]


@pytest.mark.parametrize(
    "target,may_settle", [("stage", True), ("prod", False), ("", False)]
)
def test_manual_acceptance_remains_open_on_its_own_target(
    test_db, monkeypatch, target, may_settle
):
    from yoke_core.domain.deployment_run_auto_completion import _readiness

    _isolate_status_effects(monkeypatch)
    item_id = 9756
    sources = _production_delivered(test_db, item_id)
    test_db.execute(
        "UPDATE qa_requirements SET qa_phase='manual_acceptance',execution_target_json=NULL,target_env=%s "
        "WHERE id=%s",
        (target, sources["stage"]),
    )
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='member-qa' WHERE id='run-prod'"
    )
    test_db.commit()
    test_db.execute(
        "UPDATE deployment_run_items SET delivery_intent='final' WHERE run_id='run-prod'"
    )
    test_db.commit()
    release_seeded_driver(test_db, "run-prod")
    ready, reason = _readiness(test_db, "run-prod")
    assert (ready is not None) is may_settle, reason
    assert (
        owes_only_other_targets(test_db, run_id="run-prod", item_id=item_id)
        is may_settle
    )
    if may_settle:
        mark_settling(test_db, "run-prod")
        assert settle_members(test_db, "run-prod") is None
    else:
        assert f"requirement {sources['stage']}" in reason
        assert "manual_acceptance" in reason
    requirement = test_db.execute(
        "SELECT waived_at,retracted_at FROM qa_requirements WHERE id=%s",
        (sources["stage"],),
    ).fetchone()
    assert requirement[0] is None and requirement[1] is None
    assert _item(test_db, item_id)["status"] == "release"
    assert (
        test_db.execute(
            "SELECT count(*) FROM qa_runs WHERE qa_requirement_id=%s AND verdict='pass'",
            (sources["stage"],),
        ).fetchone()[0]
        == 0
    )
