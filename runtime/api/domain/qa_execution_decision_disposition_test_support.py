# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.domain.qa_plan_execution_authority_test_support import (
    _materialize_two_cases,
)

from runtime.api.fixtures.pg_testdb import test_database

from yoke_core.domain.decision_request_disposition import (
    dispose_ended_decision_requests,
)

from yoke_core.domain.decision_request_resolution import (
    withdraw_for_ended_subject,
)

from yoke_core.domain.qa_plan_execution_lifecycle import (
    reap_stale_plan_executions,
)

from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
    lock_plan_execution,
)

from yoke_core.domain.qa_review_requests import ensure_qa_review_request


def _undetermined_walk(conn, *, item_id: int, session_id: str) -> tuple[dict, int]:
    """Walk one case to an undetermined verdict and raise its review request.

    Records the run's own id on the case's durable result, the same way a
    real capture does, so the review request it raises is bound to this
    execution through the existing relation the disposal check reads.
    """
    requirement_ids = _materialize_two_cases(conn, item_id=item_id)
    requirement_id = requirement_ids[0]
    execution = begin_plan_execution(
        conn,
        item_id=item_id,
        transition_id="implemented",
        actor_id="7",
        session_id=session_id,
    )
    run_id = conn.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "started_at, completed_at, created_at) "
        "VALUES (%s, 'agent', 'plan_case', 'undetermined', "
        "'The walker never reached the surface.', "
        "'2026-07-28T18:42:00Z', '2026-07-28T18:42:00Z', "
        "'2026-07-28T18:42:00Z') RETURNING id",
        (requirement_id,),
    ).fetchone()[0]
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "undetermined",
            "run_id": int(run_id),
        },
    )
    request, created = ensure_qa_review_request(
        conn,
        requirement_id=int(requirement_id),
        run_id=int(run_id),
    )
    assert created is True and request is not None
    return execution, int(request["id"])


def _status(conn, request_id: int) -> tuple[str, str]:
    row = conn.execute(
        "SELECT status, withdrawal_reason FROM decision_requests WHERE id=%s",
        (request_id,),
    ).fetchone()
    return str(row[0]), str(row[1] or "")
