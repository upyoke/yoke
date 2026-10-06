"""Legacy run-wide QA answers for the delivered members at settlement."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _project,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import HOLDER_A, HOLDER_B
from runtime.api.domain.test_no_obligation_member_close_out import _ready_member
from runtime.api.domain.test_run_success_member_settlement import (
    FIRST_ITEM,
    SECOND_ITEM,
    _claim_held,
    _executing_run,
    _run,
    _status,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.domain.test_dash_post_deploy_done_consumption import _bind_original
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement, insert_qa_run
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_flow_policy import (
    LEGACY_DEFINITION_SCHEMA_VERSION,
    RELEASE_POLICY_SCHEMA_VERSION,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.no_obligation_member_close_out import satisfied_delivery_member


def _legacy_run(conn, run_id, members):
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id,project_id,name,stages,created_at,definition_schema_version) "
        "VALUES (%s,1,%s,'[]',%s,%s)",
        (
            COMPLETION_FLOW,
            COMPLETION_FLOW,
            iso8601_now(),
            LEGACY_DEFINITION_SCHEMA_VERSION,
        ),
    )
    _executing_run(conn, run_id, members)


def _requirement(conn, run_id, *, member=None, verdict=None):
    requirement_id = insert_qa_requirement(
        conn,
        item_id=None,
        deployment_run_id=run_id,
        deployment_member_item_id=member,
        deployment_stage="item-qa" if member is not None else None,
        qa_kind="method_case",
        qa_phase="post_deploy",
        blocking_mode="blocking",
    )["id"]
    if verdict is not None:
        insert_qa_run(
            conn,
            qa_requirement_id=requirement_id,
            qa_kind="method_case",
            verdict=verdict,
        )
    return requirement_id


def test_passing_legacy_run_qa_settles_all_delivered_members(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    for item_id, holder in ((FIRST_ITEM, HOLDER_A), (SECOND_ITEM, HOLDER_B)):
        _ready_member(test_db, item_id, holder)
    run_id = "run-legacy-passing"
    _legacy_run(test_db, run_id, (FIRST_ITEM, SECOND_ITEM))
    requirement_id = _requirement(test_db, run_id, verdict="pass")

    assert cmd_update(run_id, "status", "succeeded") is None

    assert _run(test_db, run_id) == ("succeeded", True)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        assert _status(test_db, item_id) == "done"
        assert not _claim_held(test_db, item_id)
    row = test_db.execute(
        "SELECT waived_at,deployment_member_item_id FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    assert row["waived_at"] is None and row["deployment_member_item_id"] is None


@pytest.mark.parametrize("verdict", ["fail", None])
def test_unanswered_legacy_run_qa_holds_settlement(test_db, monkeypatch, verdict):
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    run_id = "run-legacy-unanswered"
    _legacy_run(test_db, run_id, (FIRST_ITEM,))
    _requirement(test_db, run_id, verdict=verdict)

    refusal = cmd_update(run_id, "status", "succeeded")

    assert refusal is not None
    assert _run(test_db, run_id)[0] == "executing"
    assert _status(test_db, FIRST_ITEM) == "release"
    assert _claim_held(test_db, FIRST_ITEM)


@pytest.mark.parametrize("verdict", ["pass", "fail", None])
def test_superseded_legacy_obligation_follows_its_successor(test_db, verdict):
    _project(test_db)
    _member_at_release_wait(test_db, FIRST_ITEM)
    run_id = "run-legacy-superseded"
    _legacy_run(test_db, run_id, (FIRST_ITEM,))
    original_id = _requirement(test_db, run_id, verdict="fail")
    successor_id = _requirement(test_db, run_id, verdict=verdict)
    test_db.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=%s WHERE id=%s",
        (successor_id, original_id),
    )
    test_db.commit()

    assert satisfied_delivery_member(test_db, item_id=FIRST_ITEM, run_id=run_id) is (
        verdict == "pass"
    )


def test_scoped_run_requires_the_members_own_qa(test_db):
    _project(test_db)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        _member_at_release_wait(test_db, item_id)
    run_id = "run-scoped-exact-member"
    _legacy_run(test_db, run_id, (FIRST_ITEM, SECOND_ITEM))
    test_db.execute(
        "UPDATE deployment_flows SET definition_schema_version=%s WHERE id=%s",
        (RELEASE_POLICY_SCHEMA_VERSION, COMPLETION_FLOW),
    )
    test_db.commit()
    _requirement(test_db, run_id, verdict="pass")
    _requirement(test_db, run_id, member=SECOND_ITEM, verdict="pass")
    assert not satisfied_delivery_member(test_db, item_id=FIRST_ITEM, run_id=run_id)
    own_id = _requirement(test_db, run_id, member=FIRST_ITEM)
    assert not satisfied_delivery_member(test_db, item_id=FIRST_ITEM, run_id=run_id)
    insert_qa_run(test_db, qa_requirement_id=own_id, verdict="pass")
    assert satisfied_delivery_member(test_db, item_id=FIRST_ITEM, run_id=run_id)


def test_legacy_qa_counts_only_for_members_on_that_run(test_db):
    _project(test_db)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        _member_at_release_wait(test_db, item_id)
    run_id = "run-legacy-membership"
    _legacy_run(test_db, run_id, (FIRST_ITEM,))
    _requirement(test_db, run_id, verdict="pass")
    assert not satisfied_delivery_member(test_db, item_id=SECOND_ITEM, run_id=run_id)
    other_run = "run-legacy-other"
    _executing_run(test_db, other_run, (FIRST_ITEM,))
    assert not satisfied_delivery_member(test_db, item_id=FIRST_ITEM, run_id=other_run)


@pytest.mark.parametrize("verdict", ["pass", "fail", None])
def test_unkeyed_legacy_run_qa_controls_source_terminal_done(
    test_db, monkeypatch, verdict
):
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    source_id = _bind_original(test_db, item_id=FIRST_ITEM)
    run_id = "run-legacy-source-done"
    _legacy_run(test_db, run_id, (FIRST_ITEM,))
    copy_id = _requirement(test_db, run_id, verdict=verdict)
    shape = test_db.execute(
        "SELECT plan_id,plan_case_key,deployment_member_item_id,deployment_stage "
        "FROM qa_requirements WHERE id=%s",
        (copy_id,),
    ).fetchone()
    assert all(value is None for value in shape)
    snapshot = test_db.execute(
        "SELECT requirement_snapshot,composition_frozen_at FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    assert all(value is None for value in snapshot)

    refusal = cmd_update(run_id, "status", "succeeded")

    if verdict == "pass":
        assert refusal is None
        assert _status(test_db, FIRST_ITEM) == "done"
        assert source_obligation_consumed(
            test_db, item_id=FIRST_ITEM, source_requirement_id=source_id
        )
    else:
        assert refusal is not None
        assert _status(test_db, FIRST_ITEM) == "release"
    for requirement_id in (source_id, copy_id):
        assert (
            test_db.execute(
                "SELECT waived_at FROM qa_requirements WHERE id=%s", (requirement_id,)
            ).fetchone()[0]
            is None
        )


@pytest.mark.parametrize("successor_verdict", ["pass", "fail", None])
def test_legacy_source_supersession_requires_settled_successor(
    test_db, successor_verdict
):
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    source_id = _bind_original(test_db, item_id=FIRST_ITEM)
    run_id = "run-legacy-source-supersession"
    _legacy_run(test_db, run_id, (FIRST_ITEM,))
    copy_id = _requirement(test_db, run_id, verdict="fail")
    successor_id = _requirement(test_db, run_id, verdict=successor_verdict)
    test_db.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=%s WHERE id=%s",
        (successor_id, copy_id),
    )
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    assert source_obligation_consumed(
        test_db, item_id=FIRST_ITEM, source_requirement_id=source_id
    ) is (successor_verdict == "pass")


def test_legacy_unsettled_duplicate_and_zero_copies_block_source(test_db):
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    source_id = _bind_original(test_db, item_id=FIRST_ITEM)
    run_id = "run-legacy-source-duplicates"
    _legacy_run(test_db, run_id, (FIRST_ITEM,))
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    assert not source_obligation_consumed(
        test_db, item_id=FIRST_ITEM, source_requirement_id=source_id
    )
    _requirement(test_db, run_id, verdict="pass")
    _requirement(test_db, run_id)
    assert not source_obligation_consumed(
        test_db, item_id=FIRST_ITEM, source_requirement_id=source_id
    )


def test_scoped_run_does_not_credit_run_wide_source(test_db):
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    source_id = _bind_original(test_db, item_id=FIRST_ITEM)
    run_id = "run-scoped-source-run-wide"
    _legacy_run(test_db, run_id, (FIRST_ITEM,))
    _requirement(test_db, run_id, verdict="pass")
    test_db.execute(
        "UPDATE deployment_flows SET definition_schema_version=%s WHERE id=%s",
        (RELEASE_POLICY_SCHEMA_VERSION, COMPLETION_FLOW),
    )
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    assert not source_obligation_consumed(
        test_db, item_id=FIRST_ITEM, source_requirement_id=source_id
    )


def test_waived_legacy_run_obligation_settles_source(test_db):
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    source_id = _bind_original(test_db, item_id=FIRST_ITEM)
    run_id = "run-legacy-source-waived"
    _legacy_run(test_db, run_id, (FIRST_ITEM,))
    copy_id = _requirement(test_db, run_id, verdict="fail")
    test_db.execute(
        "UPDATE qa_requirements SET waived_at=%s WHERE id=%s", (iso8601_now(), copy_id)
    )
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    assert source_obligation_consumed(
        test_db, item_id=FIRST_ITEM, source_requirement_id=source_id
    )
