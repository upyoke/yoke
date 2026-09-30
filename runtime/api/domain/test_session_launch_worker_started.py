"""Both settlement paths agree on what "the worker started" means."""

from __future__ import annotations

from yoke_core.domain.session_launch_abandonment import (
    ABANDONED_RESULT_CODE,
    settle_abandoned_launch,
    settle_launch_native_death,
)
from yoke_core.domain.session_launch_store import get_launch

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    launch_connection,
)
from runtime.api.domain.session_launch_worker_test_support import (
    LAUNCH_WORKER_SESSION as WORKER,
    add_worker_activity_tables,
    delivered_launch,
)


def _worked_without_claiming(conn) -> None:
    """Stamp the marker a completed tool call leaves, and nothing else."""
    conn.execute(
        "UPDATE harness_sessions SET first_completed_work_at=? WHERE session_id=?",
        (NOW, WORKER),
    )
    conn.commit()


def test_a_claim_free_mandate_that_completed_keeps_its_launch_at_session_end() -> None:
    """A mandate may forbid claiming, and completing it is still starting.

    A delivery probe told to read and acknowledge one message then stop
    ends with no claim and no message sent. Judging session end on the
    claim alone flipped such launches to abandoned and told the requester
    to restaff work that was already done.
    """
    conn = launch_connection()
    add_worker_activity_tables(conn)
    add_relay(conn)
    launch = delivered_launch(conn)
    _worked_without_claiming(conn)

    settled = settle_abandoned_launch(
        conn, WORKER, end_reason="session_ended", now=NOW
    )

    assert settled is None
    assert get_launch(conn, launch.launch_id).state == "succeeded"


def test_the_same_evidence_decides_a_verified_native_death() -> None:
    """Neither path may reach a different verdict on one session's facts."""
    conn = launch_connection()
    add_worker_activity_tables(conn)
    add_relay(conn)
    launch = delivered_launch(conn)
    _worked_without_claiming(conn)

    settled = settle_launch_native_death(conn, WORKER, {"native_stderr_tail": ""})

    assert settled is None
    assert get_launch(conn, launch.launch_id).state == "succeeded"


def test_a_worker_that_never_completed_a_call_is_still_abandoned() -> None:
    """The marker's absence keeps meaning what it always meant."""
    conn = launch_connection()
    add_worker_activity_tables(conn)
    add_relay(conn)
    launch = delivered_launch(conn)

    settled = settle_abandoned_launch(
        conn, WORKER, end_reason="session_ended", now=NOW
    )

    assert settled is not None
    assert settled.result_code == ABANDONED_RESULT_CODE
    assert get_launch(conn, launch.launch_id).state == "failed"
