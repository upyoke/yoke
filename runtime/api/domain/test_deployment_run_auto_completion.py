"""Settled delivery finishes a run without a second deployment driver."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_independent_member_delivery_close_out import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _settle,
    _status,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from yoke_core.domain.deployment_run_auto_completion import finish_ready_run


def _run_status(conn: Any, run_id: str) -> str:
    return str(
        conn.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()["status"]
    )


def _held_lock(monkeypatch) -> None:
    from yoke_core.domain import coordination_claims

    monkeypatch.setattr(coordination_claims, "active_claim", lambda *_args: object())


def test_independent_members_finish_run_after_both_close(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-independent-auto-finish"
    _seed_final_run(test_db, run_id, shared_qa=False)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    assert _status(test_db, MEMBER_A) == "done"
    assert _status(test_db, MEMBER_B) == "release"
    assert _run_status(test_db, run_id) == "executing"

    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_B)
    _held_lock(monkeypatch)
    result = finish_ready_run(test_db, run_id)

    assert result.completed, result
    assert _run_status(test_db, run_id) == "succeeded"
    assert (_status(test_db, MEMBER_A), _status(test_db, MEMBER_B)) == (
        "done",
        "done",
    )
    assert not finish_ready_run(test_db, run_id).completed


def test_shared_qa_keeps_members_until_all_subjects_pass(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-shared-auto-finish"
    _seed_final_run(test_db, run_id, shared_qa=True)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_B)
    _held_lock(monkeypatch)

    waiting = finish_ready_run(test_db, run_id)
    assert not waiting.completed
    assert "run-qa" in waiting.waiting
    assert (_status(test_db, MEMBER_A), _status(test_db, MEMBER_B)) == (
        "release",
        "release",
    )
    assert _run_status(test_db, run_id) == "executing"

    test_db.execute(
        "UPDATE deployment_runs SET current_stage='run-qa' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    _settle(test_db, run_id=run_id, stage="run-qa", member=None, may_complete_run=True)
    assert _run_status(test_db, run_id) == "succeeded"
    assert (_status(test_db, MEMBER_A), _status(test_db, MEMBER_B)) == (
        "done",
        "done",
    )


def test_approval_and_live_driver_prevent_parallel_completion(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-approval-auto-hold"
    _seed_final_run(test_db, run_id, shared_qa=False, shared_approval=True)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_B)
    _held_lock(monkeypatch)

    approval = finish_ready_run(test_db, run_id)
    assert "approve-release" in approval.waiting
    assert _run_status(test_db, run_id) == "executing"

    from yoke_core.domain import deployment_run_driver_attachment

    monkeypatch.setattr(
        deployment_run_driver_attachment,
        "live_attachment_for_run",
        lambda *_args, **_kwargs: type("Driver", (), {"session_id": "live-driver"})(),
    )
    attached = finish_ready_run(test_db, run_id)
    assert "live-driver" in attached.waiting
    assert _run_status(test_db, run_id) == "executing"


def test_failed_blocking_qa_does_not_complete_run(test_db: Any, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-failed-qa-auto-hold"
    _seed_final_run(test_db, run_id, shared_qa=False)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_B)
    test_db.execute(
        "INSERT INTO deployment_run_qa(run_id,check_name,source,blocking,status) "
        "VALUES (%s,'smoke','flow_default',1,'failed')",
        (run_id,),
    )
    test_db.commit()
    _held_lock(monkeypatch)

    result = finish_ready_run(test_db, run_id)

    assert "smoke" in result.waiting
    assert _run_status(test_db, run_id) == "executing"
