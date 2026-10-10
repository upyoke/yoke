"""Removed member owners receive cancellation, never a QA-pass notice."""

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
from yoke_core.domain.deployment_runs_crud_mutate import cmd_remove_item
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_gates import GateTarget, check_done_gate


def test_removal_tells_the_holder_even_when_remaining_run_succeeds(
    test_db, monkeypatch
):
    _project(test_db)
    _red_member(test_db)
    _parked_owner(test_db, HOLDER_A, ITEM)

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
