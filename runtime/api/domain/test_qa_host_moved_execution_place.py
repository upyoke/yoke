"""A moved QA execution keeps its host-line place until its successor opens item QA.

The measured miss (YOK-5491, run-20261119-016): a takeover moved a waiting
item-QA execution to a successor still at hosted-release. The host was
reserved for it anyway, its resume refused ``qa_item_stage_not_open``, and
releasing the turn aborted it ``qa_host_turn_released``, so its rerun joined
the back of the line. It lost its place three times in one day.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_host_turns_test_support import MACHINE, _notices
from runtime.api.domain.test_deployment_qa_execution_refreeze import (
    _order,
    _queued_then_taken_over,
    _redeploy_new,
)
from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.deployment_qa_execution_refreeze import resume_moved_execution
from yoke_core.domain.qa_host_set_turns import record_host_wait
from yoke_core.domain.qa_host_turn_release import HOST_TURN_RELEASED_REASON
from yoke_core.domain.qa_host_turns import HOST_TURN_REASON, join_host_queue
from yoke_core.domain.qa_plan_execution_store import select_plan_execution
from yoke_core.domain.work_claim_targets import make_qa_admission_target

HOLDER, LATER, LAST = "host-holder", "later-waiter", "last-waiter"
TARGET = make_qa_admission_target(MACHINE)


def _line(conn, monkeypatch, *, held: bool):
    """The moved execution queued first; two manual waiters queued after it."""
    moved = _queued_then_taken_over(conn, monkeypatch)
    seed_qa_session(conn, takeover.DRIVER_SESSION, HOLDER, LATER, LAST)
    if held:
        acquire(conn, TARGET, HOLDER, commit=False)
    start = utc_now() - timedelta(hours=1)
    wait = join_host_queue(
        conn,
        TARGET,
        session_id=takeover.DRIVER_SESSION,
        actor_id=1,
        resume_command="unused for plan executions",
        execution_id=str(moved["id"]),
        queued_at=start,
    )
    for offset, session in ((1, LATER), (2, LAST)):
        join_host_queue(
            conn,
            TARGET,
            session_id=session,
            actor_id=1,
            resume_command="yoke claims coordination acquire QA_HOST:linux-lab",
            queued_at=start + timedelta(minutes=offset),
        )
    conn.commit()
    return moved, wait


def _wait(conn, wait_id):
    return conn.execute(
        "SELECT state,claim_id,queued_at FROM qa_test_machine_waits WHERE id=%s",
        (wait_id,),
    ).fetchone()


def _reserved_session(conn) -> str:
    claim = active_claim(conn, TARGET)
    assert claim is not None and claim.reason.startswith(HOST_TURN_REASON)
    return str(claim.session_id)


def test_release_passes_over_a_moved_execution_before_its_stage_opens(
    test_db, monkeypatch
) -> None:
    _notices(monkeypatch)
    moved, wait = _line(test_db, monkeypatch, held=True)
    order = _order(test_db, moved["id"])

    release(test_db, active_claim(test_db, TARGET).id, "done walking")

    assert _reserved_session(test_db) == LATER
    kept = _wait(test_db, wait["id"])
    assert kept["state"] == "waiting" and kept["claim_id"] is None
    assert parse_instant(kept["queued_at"]) == parse_instant(wait["queued_at"])
    execution = select_plan_execution(test_db, moved["id"], lock=False)
    assert execution["state"] == "waiting"
    assert _order(test_db, moved["id"]) == order

    # Item QA opens; the owner's `yoke qa plan run` re-freezes the same
    # execution, and its walk queues behind the reserved lease at its place.
    _redeploy_new(test_db)
    resumed = resume_moved_execution(
        test_db,
        execution,
        SimpleNamespace(checkout_path=None, expected_branch=None, test_machine=None),
        SimpleNamespace(actor_id="1", session_id=takeover.DRIVER_SESSION),
    )
    assert resumed is not None and resumed["id"] == moved["id"]
    queued = record_host_wait(
        test_db, resumed, test_machine=MACHINE, rationale="lease held"
    )
    assert parse_instant(queued["host_wait"]["queued_at"]) == parse_instant(
        wait["queued_at"]
    )
    assert queued["host_wait"]["position"] == 1

    release(test_db, active_claim(test_db, TARGET).id, "not needed")

    assert _reserved_session(test_db) == takeover.DRIVER_SESSION
    assert _order(test_db, moved["id"]) == order


def test_released_reservation_of_a_moved_execution_returns_it_to_its_place(
    test_db, monkeypatch
) -> None:
    _notices(monkeypatch)
    moved, wait = _line(test_db, monkeypatch, held=False)
    order = _order(test_db, moved["id"])
    # The host was reserved for the execution before the takeover moved it.
    claim = acquire(
        test_db,
        TARGET,
        takeover.DRIVER_SESSION,
        reason=HOST_TURN_REASON + str(wait["id"]),
        commit=False,
    )
    test_db.execute(
        "UPDATE qa_test_machine_waits SET state='reserved',claim_id=%s WHERE id=%s",
        (claim.id, wait["id"]),
    )
    test_db.commit()

    release(test_db, claim.id, "stage not open")

    kept = _wait(test_db, wait["id"])
    assert kept["state"] == "waiting" and kept["claim_id"] is None
    assert parse_instant(kept["queued_at"]) == parse_instant(wait["queued_at"])
    execution = select_plan_execution(test_db, moved["id"], lock=False)
    assert execution["state"] == "waiting"
    assert HOST_TURN_RELEASED_REASON not in str(execution.get("release_reason") or "")
    assert _order(test_db, moved["id"]) == order
    assert _reserved_session(test_db) == LATER
