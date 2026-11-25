"""A bounded call behind a held execution row refuses by name instead of queueing."""

from __future__ import annotations

from contextlib import contextmanager
from time import monotonic

import pytest

from runtime.api.domain.qa_execution_request_subject_test_support import (
    SESSION,
    _shared_execution,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import qa_plan_execution_store, qa_plan_lock
from yoke_core.domain.yoke_function_dispatch import dispatch

PRODUCTION_LOCK_S = qa_plan_lock.QA_PLAN_LOCK_TIMEOUT_MS / 1000
PAUSE = {"phase": "checkin", "cursor": 0, "request_id": "behind-lock", "attempts": []}
SUBMIT = {"bundle_id": "bundle-behind-lock", "bundle_digest": "0" * 64}


@pytest.mark.parametrize(
    ("function", "payload"),
    [
        ("qa.plan_execution.pause", PAUSE),
        ("qa.plan_execution.abort", {"reason": "abort behind lock"}),
        ("qa.plan_review.submit", SUBMIT),
    ],
)
def test_bounded_call_refuses_with_recovery_when_the_execution_row_stays_locked(
    test_db, function, payload, monkeypatch
):
    lock_spans = []
    bounded_plan_lock = qa_plan_execution_store.bounded_plan_lock

    @contextmanager
    def timed_plan_lock(conn, table):
        started = monotonic()
        try:
            with bounded_plan_lock(conn, table):
                yield
        finally:
            lock_spans.append(monotonic() - started)

    monkeypatch.setattr(qa_plan_execution_store, "bounded_plan_lock", timed_plan_lock)
    monkeypatch.setattr(qa_plan_lock, "QA_PLAN_LOCK_TIMEOUT_MS", 100)
    run_id = "run-execution-lock-bound"
    execution = _shared_execution(test_db, run_id, (9301, 9302))
    holder = connect_test_database(test_db.info.dbname)
    try:
        holder.execute(
            "SELECT id FROM qa_plan_executions WHERE id=%s FOR UPDATE",
            (str(execution["id"]),),
        )
        started = monotonic()
        response = dispatch(
            FunctionCallRequest(
                function=function,
                actor=ActorContext(
                    actor_id=str(execution["actor_id"]), session_id=SESSION
                ),
                target=TargetRef(kind="global", project_id="yoke"),
                payload={"execution_id": str(execution["id"]), **payload},
            )
        )
        waited = monotonic() - started
    finally:
        holder.rollback()
        holder.close()

    assert not response.success
    assert response.error.code == "qa_plan_busy"
    assert response.error.message.startswith("qa_plan_busy:")
    assert "Retry the same command" in response.error.message
    assert len(lock_spans) == 1
    assert 0.1 <= lock_spans[0] < 0.5
    assert 0.1 <= waited < PRODUCTION_LOCK_S
    state, reason = test_db.execute(
        "SELECT state,release_reason FROM qa_plan_executions WHERE id=%s",
        (str(execution["id"]),),
    ).fetchone()
    assert state == execution["state"]
    assert (reason or None) == (execution.get("release_reason") or None)
