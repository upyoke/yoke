"""The run-scoped QA wait notice, delivered for real.

The item-scoped counterpart (and the shared claim/session/message
helpers both files use) lives in
``test_deployment_qa_stage_wake_delivery.py``; split out only to keep
each file under the authored line budget.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.coordination_claim_test_support import PROJECT_YOKE
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_run_driver_attachment import (
    PHASE_EXECUTING,
    attach_driver,
)
from yoke_core.domain.deployment_qa_stage_wake import (
    notify_run_scoped_qa_wait,
    run_stage_wait_idempotency_key,
)

STEERING_SESSION = "sess-steering"
DRIVER_SESSION = "sess-driver"


def _driven_run(conn: Any, run_id: str, session_id: str) -> None:
    """An executing run whose live driver is *session_id*."""
    conn.execute(
        "INSERT INTO deployment_runs (id,project_id,flow,status,created_at) "
        "VALUES (%s,%s,'flow-wake','executing',%s)",
        (run_id, PROJECT_YOKE, iso8601_now()),
    )
    attach_driver(conn, run_id, session_id=session_id, pid=4242, phase=PHASE_EXECUTING)
    conn.commit()


def test_run_scoped_wake_reaches_the_runs_live_driver(test_db: Any) -> None:
    _project(test_db)
    seed_session(test_db, DRIVER_SESSION)
    seed_session(test_db, STEERING_SESSION)
    _claim(
        test_db,
        session_id=STEERING_SESSION,
        target_kind="steering",
        scope_json='{"project_id": %d}' % PROJECT_YOKE,
    )
    _driven_run(test_db, "run-wd-4", DRIVER_SESSION)

    result = notify_run_scoped_qa_wait(
        test_db,
        run_id="run-wd-4",
        stage_name="run-qa",
        project_id=PROJECT_YOKE,
        reasons="awaiting agent verdict",
        names_cases=True,
        target_tier="ephemeral",
        revision="b" * 40,
    )

    assert result in ("delivered", "undelivered")
    key = run_stage_wait_idempotency_key("run-wd-4", "run-qa")
    assert _recipients(test_db, key) == [DRIVER_SESSION]
    [body] = _bodies(test_db, key)
    assert "run-wd-4" in body
    assert "ephemeral" in body


def test_run_scoped_wake_falls_back_to_the_plain_project_steering_seat(
    test_db: Any,
) -> None:
    _project(test_db)
    seed_session(test_db, STEERING_SESSION)
    _claim(
        test_db,
        session_id=STEERING_SESSION,
        target_kind="steering",
        scope_json='{"project_id": %d}' % PROJECT_YOKE,
    )

    result = notify_run_scoped_qa_wait(
        test_db,
        run_id="run-wd-5",
        stage_name="run-qa",
        project_id=PROJECT_YOKE,
        reasons="awaiting agent verdict",
        names_cases=True,
    )

    assert result in ("delivered", "undelivered")
    key = run_stage_wait_idempotency_key("run-wd-5", "run-qa")
    assert _recipients(test_db, key) == [STEERING_SESSION]


def test_run_scoped_wake_does_not_guess_among_document_scoped_seats(
    test_db: Any,
) -> None:
    """A project can carry a steering seat narrowed to one strategy document
    (e.g. a release-planning doc) alongside -- or instead of -- its plain
    seat. Run-scoped work names no document, so it must not be routed to a
    document-narrowed seat as if it were the project's general seat."""
    _project(test_db)
    seed_session(test_db, STEERING_SESSION)
    _claim(
        test_db,
        session_id=STEERING_SESSION,
        target_kind="steering",
        scope_json='{"project_id": %d, "document": "RELEASES"}' % PROJECT_YOKE,
    )

    result = notify_run_scoped_qa_wait(
        test_db,
        run_id="run-wd-6",
        stage_name="run-qa",
        project_id=PROJECT_YOKE,
        reasons="awaiting agent verdict",
        names_cases=True,
    )

    assert result == ""
    assert (
        _recipients(test_db, run_stage_wait_idempotency_key("run-wd-6", "run-qa")) == []
    )
