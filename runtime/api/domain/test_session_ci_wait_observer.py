"""The sweep that hands a stopped worker the verdict its CI run produced."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import (
    INJECTED_AT,
    inject,
    message_body,
    message_count,
    message_id_for,
)
from runtime.api.domain.test_session_message_support import message_connection
from yoke_core.domain.session_ci_wait_observer import (
    apply_received_wait,
    observe_pending_ci_runs,
)
from yoke_core.domain.session_ci_wait_schema import ensure_session_ci_wait_schema

NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
SESSION = "s1"
RUN_ID = "33903192687"
HEAD_SHA = "ab" * 20
NOTICE_KEY = f"ci-run-concluded:{SESSION}:{RUN_ID}"


@pytest.fixture()
def waiting_connection():
    """One session owed one pending CI verdict."""
    conn = message_connection()
    ensure_session_ci_wait_schema(conn)
    conn.execute(
        "INSERT INTO session_ci_run_waits "
        "(session_id,project_id,repo,run_id,head_sha,kind,continue_command,"
        "created_at) VALUES (?,1,'acme/widgets',?,?,'selection',?,?)",
        (
            SESSION,
            RUN_ID,
            HEAD_SHA,
            "yoke watch pytest --impacted main --bounded",
            "2026-09-04T17:40:00Z",
        ),
    )
    conn.commit()
    return conn


def concluded(_project, _repo, _run_id):
    return "completed", "success", ""


def still_running(_project, _repo, _run_id):
    return "in_progress", "", ""


def _wait_row(conn):
    return conn.execute(
        "SELECT conclusion, notified_at, read_at FROM session_ci_run_waits"
    ).fetchone()


def test_a_concluded_run_carries_its_verdict_to_the_waiting_session(
    waiting_connection,
) -> None:
    result = observe_pending_ci_runs(
        waiting_connection, [1], now=NOW, read_run=concluded
    )

    assert result["concluded"] == 1
    body = message_body(waiting_connection, message_id_for(waiting_connection, NOTICE_KEY))
    assert "CI verdict: success" in body
    assert RUN_ID in body
    assert "yoke watch pytest --impacted main --bounded" in body
    assert _wait_row(waiting_connection)["conclusion"] == "success"


def test_repeated_sweeps_send_one_notice_and_stop_once_it_lands(
    waiting_connection,
) -> None:
    observe_pending_ci_runs(waiting_connection, [1], now=NOW, read_run=concluded)
    inject(waiting_connection, message_id_for(waiting_connection, NOTICE_KEY))

    delivered = observe_pending_ci_runs(
        waiting_connection, [1], now=INJECTED_AT, read_run=concluded
    )

    assert delivered["notified"] == 1
    assert message_count(waiting_connection) == 1
    assert _wait_row(waiting_connection)["notified_at"]
    # The wait has left the candidate set, so a later sweep reads nothing.
    assert observe_pending_ci_runs(
        waiting_connection, [1], now=INJECTED_AT, read_run=concluded
    )["checked"] == 0


def test_a_session_whose_turn_is_in_flight_is_not_woken(waiting_connection) -> None:
    waiting_connection.execute(
        "UPDATE harness_sessions SET turn_posture='running' WHERE session_id=?",
        (SESSION,),
    )
    waiting_connection.commit()

    def refuse(*_args):  # pragma: no cover - the assertion is that it is unused
        raise AssertionError("a session reading the run itself must not be polled")

    result = observe_pending_ci_runs(
        waiting_connection, [1], now=NOW, read_run=refuse
    )

    assert result["in_flight_sessions"] == 1
    assert message_count(waiting_connection) == 0
    assert _wait_row(waiting_connection)["read_at"] is None


def test_a_run_still_in_flight_produces_no_notice(waiting_connection) -> None:
    result = observe_pending_ci_runs(
        waiting_connection, [1], now=NOW, read_run=still_running
    )

    assert result["concluded"] == 0
    assert message_count(waiting_connection) == 0
    assert _wait_row(waiting_connection)["read_at"] == "2026-09-04T18:00:00Z"


def test_a_merge_boundary_wait_names_itself_accurately_and_teaches_resume(
    waiting_connection,
) -> None:
    """The merge boundary's own CI run is neither a selection nor a QA case."""
    # "s2" is one of the base fixture's ordinary, non-running sessions —
    # reused here rather than inserted, since the schema's session_id
    # primary key would collide with the fixture's own row for it.
    merge_session = "s2"
    merge_run_id = "44904203798"
    waiting_connection.execute(
        "INSERT INTO session_ci_run_waits "
        "(session_id,project_id,repo,run_id,head_sha,kind,continue_command,"
        "created_at) VALUES (?,1,'acme/widgets',?,?,'merge_verification',?,?)",
        (
            merge_session,
            merge_run_id,
            HEAD_SHA,
            "yoke merge item ACME-9",
            "2026-09-04T17:41:00Z",
        ),
    )
    waiting_connection.commit()

    result = observe_pending_ci_runs(
        waiting_connection, [1], now=NOW, read_run=concluded
    )

    assert result["concluded"] == 2
    body = message_body(
        waiting_connection,
        message_id_for(
            waiting_connection, f"ci-run-concluded:{merge_session}:{merge_run_id}"
        ),
    )
    assert "merge verification CI run" in body
    assert "pytest selection run" not in body
    assert "yoke merge item ACME-9" in body


def _apply(conn, *, session_id=SESSION, run_id=RUN_ID, conclusion="success"):
    applied = apply_received_wait(
        conn,
        session_id=session_id,
        run_id=run_id,
        conclusion=conclusion,
        now="2026-09-04T17:59:00Z",
    )
    conn.commit()
    return applied


def test_a_watcher_that_already_printed_success_is_not_woken(
    waiting_connection,
) -> None:
    assert _apply(waiting_connection, conclusion="success") is True

    def refuse(*_args):  # pragma: no cover - the assertion is that it is unused
        raise AssertionError("a received wait must not be polled again")

    result = observe_pending_ci_runs(
        waiting_connection, [1], now=NOW, read_run=refuse
    )

    assert result["checked"] == 0
    assert message_count(waiting_connection) == 0
    row = _wait_row(waiting_connection)
    assert row["conclusion"] == "success"
    assert row["notified_at"] == "2026-09-04T17:59:00Z"


def test_a_watcher_that_already_printed_failure_is_not_woken(
    waiting_connection,
) -> None:
    assert _apply(waiting_connection, conclusion="failure") is True

    result = observe_pending_ci_runs(
        waiting_connection, [1], now=NOW, read_run=concluded
    )

    assert result["checked"] == 0
    assert message_count(waiting_connection) == 0
    assert _wait_row(waiting_connection)["conclusion"] == "failure"


def test_an_interrupted_watcher_still_gets_the_sweep_notice(
    waiting_connection,
) -> None:
    """Dying before the verdict lands leaves the wait pending on purpose."""
    result = observe_pending_ci_runs(
        waiting_connection, [1], now=NOW, read_run=concluded
    )

    assert result["concluded"] == 1
    assert message_count(waiting_connection) == 1
    assert _wait_row(waiting_connection)["notified_at"] is None


def test_a_second_resolve_of_the_same_wait_is_a_noop(waiting_connection) -> None:
    assert _apply(waiting_connection) is True
    assert _apply(waiting_connection, conclusion="failure") is False

    row = _wait_row(waiting_connection)
    assert row["conclusion"] == "success"
    assert row["notified_at"] == "2026-09-04T17:59:00Z"


def test_a_watcher_winning_the_sweep_race_suppresses_the_duplicate_notice(
    waiting_connection,
) -> None:
    def conclude_after_watcher(_project, _repo, _run_id):
        _apply(waiting_connection, conclusion="success")
        return "completed", "success", ""

    result = observe_pending_ci_runs(
        waiting_connection, [1], now=NOW, read_run=conclude_after_watcher
    )

    assert message_count(waiting_connection) == 0
    assert _wait_row(waiting_connection)["notified_at"]
    assert result["notified"] == 0


def test_resolving_one_wait_leaves_a_sibling_session_and_run_pending(
    waiting_connection,
) -> None:
    other_run = "44904203798"
    waiting_connection.execute(
        "INSERT INTO session_ci_run_waits "
        "(session_id,project_id,repo,run_id,head_sha,kind,continue_command,"
        "created_at) VALUES ('s2',1,'acme/widgets',?,?,'selection',?,?)",
        (other_run, HEAD_SHA, "yoke watch pytest", "2026-09-04T17:41:00Z"),
    )
    waiting_connection.commit()
    _apply(waiting_connection, conclusion="success")

    result = observe_pending_ci_runs(
        waiting_connection, [1], now=NOW, read_run=concluded
    )

    assert result["concluded"] == 1
    assert message_count(waiting_connection) == 1
    own = waiting_connection.execute(
        "SELECT notified_at FROM session_ci_run_waits "
        "WHERE session_id=? AND run_id=?",
        (SESSION, RUN_ID),
    ).fetchone()
    sibling = waiting_connection.execute(
        "SELECT notified_at FROM session_ci_run_waits "
        "WHERE session_id=? AND run_id=?",
        ("s2", other_run),
    ).fetchone()
    assert own["notified_at"]
    assert sibling["notified_at"] is None


def test_a_terminated_session_is_no_longer_a_candidate(waiting_connection) -> None:
    waiting_connection.execute(
        "UPDATE harness_sessions SET terminated_at='2026-09-04T17:50:00Z' "
        "WHERE session_id=?",
        (SESSION,),
    )
    waiting_connection.commit()

    result = observe_pending_ci_runs(
        waiting_connection, [1], now=NOW, read_run=concluded
    )

    assert result["checked"] == 0
    assert message_count(waiting_connection) == 0
