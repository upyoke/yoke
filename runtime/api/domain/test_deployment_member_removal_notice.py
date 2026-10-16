"""Removed member owners receive cancellation, never a QA-pass notice."""

import pytest

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import ITEM_QA_STAGE
from runtime.api.domain.test_deployment_run_member_removal import (
    ITEM,
    RUN,
    REASON,
    _red_member,
    _still_member,
)
from runtime.api.domain.test_deployment_delivery_close_out_notice import _parked_owner
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import HOLDER_A, _project
from yoke_core.domain import deployment_member_removal_notice as notice
from yoke_core.domain.deployment_run_member_removal import remove_member_on
from yoke_core.domain.deployment_run_target_takeover import TAKEOVER_REMOVED_BY
from yoke_core.domain.deployment_runs_crud_mutate import cmd_remove_item
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_gates import GateTarget, check_done_gate
from yoke_core.domain.qa_plan_execution_store import roster_digest
from yoke_core.domain.session_explicit_wake import explicit_stopped_wake_requested


def test_removal_tells_the_holder_even_when_remaining_run_succeeds(
    test_db, monkeypatch
):
    _project(test_db)
    _red_member(test_db)
    _parked_owner(test_db, HOLDER_A, ITEM)
    release_seeded_driver(test_db, RUN)

    cmd_remove_item(RUN, ITEM, reason=REASON, session_id="remover", actor_id=2)

    rows = test_db.execute(
        "SELECT m.body,r.session_id FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id=m.message_id "
        "WHERE m.idempotency_key LIKE %s",
        (f"removed-member:{RUN}:{ITEM}:%",),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["session_id"] == HOLDER_A
    body = rows[0]["body"]
    ref = render_item_ref(test_db, ITEM)
    assert f"{ref} was removed from run {RUN} by steering" in body
    assert "cancelled (not passed)" in body
    assert "rides a later release; do not attempt close-out" in body
    assert "re-park" in body
    assert not _still_member(test_db)
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (RUN,)
        ).fetchone()["status"]
        == "succeeded"
    )


def test_send_failure_keeps_removal_and_retraction(test_db, monkeypatch, capsys):
    requirement = _red_member(test_db)
    release_seeded_driver(test_db, RUN)

    def fail(conn, **_kwargs):
        # A real Postgres statement failure aborts the savepoint until rollback.
        conn.execute("SELECT nonexistent_removal_notice_column FROM items")

    monkeypatch.setattr(notice, "push_member_notice", fail)
    cmd_remove_item(RUN, ITEM, reason=REASON)

    assert not _still_member(test_db)
    assert test_db.execute(
        "SELECT retracted_at FROM qa_requirements WHERE id=%s", (requirement,)
    ).fetchone()["retracted_at"]
    output = capsys.readouterr().out
    assert "member_removal_notice_failed" in output
    assert "Notify its holder manually" in output


def test_done_gate_ignores_retracted_run_qa_without_calling_it_passed(
    test_db, monkeypatch
):
    requirement = _red_member(test_db)
    release_seeded_driver(test_db, RUN)
    target = GateTarget(item_id=ITEM)
    assert not check_done_gate(target, "").passed

    cmd_remove_item(RUN, ITEM, reason=REASON)

    result = check_done_gate(target, "")
    assert result.passed, result.errors
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s ORDER BY id DESC LIMIT 1",
            (requirement,),
        ).fetchone()["verdict"]
        == "fail"
    )
    # QA settlement alone never grants this removed member delivery authority.
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (ITEM,)).fetchone()[
            "status"
        ]
        == "release"
    )


def _notices(conn):
    return conn.execute(
        "SELECT m.body,r.routing_snapshot,r.wake_after,m.expires_at "
        "FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id=m.message_id "
        "WHERE m.idempotency_key LIKE %s",
        (f"removed-member:{RUN}:{ITEM}:%",),
    ).fetchall()


def _take_over(conn, *, live: bool):
    _project(conn)
    _red_member(conn)
    _parked_owner(conn, HOLDER_A, ITEM)
    release_seeded_driver(conn, RUN)
    if live:
        conn.execute(
            "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
            "deployment_member_item_id,actor_id,session_id,roster_digest,"
            "roster_json,cursor_ordinal,state,created_at,heartbeat_at) VALUES "
            "('exec-takeover-notice',%s,%s,%s,'2',%s,%s,'[]',0,'active',"
            "now(),now())",
            (RUN, ITEM_QA_STAGE, ITEM, HOLDER_A, roster_digest([])),
        )
    new_run = "run-takeover-next"
    remove_member_on(
        conn,
        RUN,
        ITEM,
        reason=(
            f"taken over by run {new_run}, whose candidate contains this run's; "
            "the member's QA continues there"
        ),
        session_id="remover",
        actor_id=2,
        removed_by=TAKEOVER_REMOVED_BY,
    )
    conn.commit()
    return new_run


def test_takeover_without_a_running_execution_sends_nothing(test_db):
    _take_over(test_db, live=False)
    assert _notices(test_db) == []


def test_takeover_that_aborts_a_running_execution_wakes_naming_the_new_run(test_db):
    new_run = _take_over(test_db, live=True)
    rows = _notices(test_db)
    assert len(rows) == 1
    body = rows[0]["body"]
    assert new_run in body
    assert "continues on the new run" in body
    assert "stay parked" in body
    assert "rides a later release" not in body
    assert "re-park" not in body
    assert explicit_stopped_wake_requested(rows[0]["routing_snapshot"])
    assert rows[0]["wake_after"] != rows[0]["expires_at"]
    assert (
        test_db.execute(
            "SELECT state FROM qa_plan_executions WHERE id=%s",
            ("exec-takeover-notice",),
        ).fetchone()["state"]
        == "aborted"
    )


@pytest.mark.parametrize("removed_by", ["item QA failure", "settlement"])
def test_qa_failure_and_settlement_notices_still_wake(test_db, removed_by):
    _project(test_db)
    _red_member(test_db)
    _parked_owner(test_db, HOLDER_A, ITEM)
    release_seeded_driver(test_db, RUN)
    remove_member_on(
        test_db,
        RUN,
        ITEM,
        reason=REASON,
        session_id="remover",
        actor_id=2,
        removed_by=removed_by,
    )
    test_db.commit()
    rows = _notices(test_db)
    assert len(rows) == 1
    assert "rides a later release; do not attempt close-out" in rows[0]["body"]
    assert "re-park" in rows[0]["body"]
    assert explicit_stopped_wake_requested(rows[0]["routing_snapshot"])
