# ruff: noqa: F811
"""What accounts for a dead process, and what still reads as one.

A machine keeps its record of a dead native until the control plane ends the
session, so a session held open by its claims is reported again on every
poll. These cases pin the two things that must not follow from a repeat: one
old exit reading as a fresh death, and a session that has demonstrably
resumed still reading as gone. They also pin the one shape a declared wait
may account for -- a native that exited normally -- and the two it may not, a
crash and an exit nobody measured.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from runtime.api.test_sessions import _insert_claimable_items, _register
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
    record_native_process_gone,
)
from yoke_core.domain.sessions import claim_work
from yoke_core.domain.sessions_holdings_claim_facts import (
    ITEM_AWAITING_LANDING_KEY,
    claimed_item_facts,
)


MACHINE = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
#: The launch that started the session's first native, and its exit.
DEAD_PROCESS = {
    "records_considered": 1,
    "sources": ["launch_handle"],
    "pids": [92967],
    "process_start_times": {"92967": "1699999999"},
    "launch_id": "9f1f2d4e-0f7a-4a71-9a1a-6a0c0b6f2d10",
}
#: A different native under the same session, dying later.
LATER_PROCESS = {
    "records_considered": 1,
    "sources": ["launch_handle"],
    "pids": [93400],
    "process_start_times": {"93400": "1700008888"},
    "launch_id": "9f1f2d4e-0f7a-4a71-9a1a-6a0c0b6f2d11",
}
#: Every activity stamp a freshly registered row carries, pinned before the
#: first death so each case states its own activity rather than "now".
BEFORE_THE_DEATH = "2026-09-09T12:00:00Z"
FIRST_SEEN = datetime(2026, 9, 9, 12, 24, 45, tzinfo=timezone.utc)
FIRST_SEEN_TEXT = "2026-09-09T12:24:45Z"
RESUMED_AT = "2026-09-09T13:56:58Z"
POLLED_AGAIN = datetime(2026, 9, 9, 14, 13, 55, tzinfo=timezone.utc)
POLLED_AGAIN_TEXT = "2026-09-09T14:13:55Z"


@pytest.fixture
def conn(test_db):
    return test_db


@pytest.fixture(autouse=True)
def _claimable_items(conn):
    _insert_claimable_items(conn, 9301)


def _row(**overrides) -> dict:
    """One session row carrying only what the observation reads."""
    row = {
        "native_process_gone_at": FIRST_SEEN_TEXT,
        "native_process_gone_evidence": json.dumps(DEAD_PROCESS),
        "last_heartbeat": "2026-09-09T12:24:40Z",
        "last_tool_call_at": "2026-09-09T12:24:40Z",
        "episode_started_at": "2026-09-09T11:00:00Z",
        "mode": "dash",
    }
    row.update(overrides)
    return row


def _evidence(**extra) -> str:
    return json.dumps({**DEAD_PROCESS, **extra})


def _session(conn, session_id: str) -> str:
    _register(conn, session_id=session_id, machine_id=MACHINE)
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s, last_tool_call_at=%s, "
        "episode_started_at=%s WHERE session_id=%s",
        (BEFORE_THE_DEATH, BEFORE_THE_DEATH, BEFORE_THE_DEATH, session_id),
    )
    conn.commit()
    return session_id


def _stored(conn, session_id: str) -> dict:
    return dict(
        conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (session_id,)
        ).fetchone()
    )


def test_re_reporting_one_death_keeps_the_time_it_was_first_seen(conn):
    """The stamp names the death, so a later poll cannot refresh an old exit."""
    session_id = _session(conn, "sess-repeat-report")

    record_native_process_gone(conn, session_id, DEAD_PROCESS, observed_at=FIRST_SEEN)
    repeat = record_native_process_gone(
        conn, session_id, DEAD_PROCESS, observed_at=POLLED_AGAIN
    )
    conn.commit()

    assert repeat["observed_at"] == FIRST_SEEN_TEXT
    assert _stored(conn, session_id)["native_process_gone_at"] == FIRST_SEEN_TEXT


def test_a_session_that_resumed_after_the_death_no_longer_reads_as_gone(conn):
    """An old successful exit, a later resume, and a fresh poll about the same
    process: the resume is what the roster must show."""
    session_id = _session(conn, "sess-resumed-after-death")
    record_native_process_gone(conn, session_id, DEAD_PROCESS, observed_at=FIRST_SEEN)
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s, last_heartbeat=%s "
        "WHERE session_id=%s",
        (RESUMED_AT, RESUMED_AT, session_id),
    )

    record_native_process_gone(conn, session_id, DEAD_PROCESS, observed_at=POLLED_AGAIN)
    conn.commit()

    assert current_native_process_observation(_stored(conn, session_id)) is None


def test_a_late_first_report_is_stamped_when_the_native_exited(conn):
    """A report can arrive long after the exit it names.

    Preserving first arrival alone would let a slow report outrank the resume
    that happened in between, so an exit time the machine actually read wins.
    """
    session_id = _session(conn, "sess-late-report")
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s, last_heartbeat=%s "
        "WHERE session_id=%s",
        (RESUMED_AT, RESUMED_AT, session_id),
    )

    record_native_process_gone(
        conn,
        session_id,
        {**DEAD_PROCESS, "native_exit_at": FIRST_SEEN_TEXT},
        observed_at=POLLED_AGAIN,
    )
    conn.commit()

    row = _stored(conn, session_id)
    assert row["native_process_gone_at"] == FIRST_SEEN_TEXT
    assert current_native_process_observation(row) is None


def test_a_later_process_dying_is_stamped_when_it_was_seen(conn):
    """A different native's death is a different death, and still alarms."""
    session_id = _session(conn, "sess-second-death")
    record_native_process_gone(conn, session_id, DEAD_PROCESS, observed_at=FIRST_SEEN)
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s, last_heartbeat=%s "
        "WHERE session_id=%s",
        (RESUMED_AT, RESUMED_AT, session_id),
    )

    record_native_process_gone(
        conn, session_id, LATER_PROCESS, observed_at=POLLED_AGAIN
    )
    conn.commit()

    observation = current_native_process_observation(_stored(conn, session_id))
    assert observation is not None
    assert observation["observed_at"] == POLLED_AGAIN_TEXT


def test_activity_at_the_moment_of_the_death_does_not_supersede_it():
    """Second-precision stamps tie; only strictly later activity is proof."""
    assert current_native_process_observation(
        _row(last_tool_call_at=FIRST_SEEN_TEXT)
    ) == {
        "state": "gone",
        "observed_at": FIRST_SEEN_TEXT,
        "evidence": DEAD_PROCESS,
    }


def test_a_normal_exit_under_a_parked_session_reads_as_the_wait():
    """A finished headless command under a declared wait is not a disappearance."""
    row = _row(mode="parked", native_process_gone_evidence=_evidence(exit_code=0))

    assert current_native_process_observation(row) is None


def test_a_normal_exit_waiting_on_a_queue_landing_reads_as_the_wait():
    row = _row(native_process_gone_evidence=_evidence(exit_code=0))

    assert current_native_process_observation(row, landing_wait=True) is None


def test_a_crash_under_a_parked_session_still_reads_as_gone():
    """A park is not a place to hide a non-zero exit."""
    row = _row(mode="parked", native_process_gone_evidence=_evidence(exit_code=1))

    assert current_native_process_observation(row) is not None


def test_an_exit_nobody_measured_under_a_parked_session_still_reads_as_gone():
    """No reading is not a clean reading."""
    assert current_native_process_observation(_row(mode="parked")) is not None


def test_a_normal_exit_with_no_wait_declared_still_reads_as_gone():
    """A worker that finished and left its claim held is worth naming."""
    row = _row(native_process_gone_evidence=_evidence(exit_code=0))

    assert current_native_process_observation(row) is not None


def test_an_armed_item_reports_its_holder_is_waiting_on_the_landing(conn):
    """The fact rides the read that already loads every claimed item's row."""
    claim_work(conn, session_id=_session(conn, "sess-armed-landing"), item_id=9301)
    conn.execute(
        "UPDATE items SET merge_queue_enqueued_at=%s WHERE id=%s",  # lint:no-lifecycle-mutation-check
        ("2026-09-09T14:00:00Z", 9301),
    )
    conn.commit()

    assert claimed_item_facts(conn, [9301])[9301][ITEM_AWAITING_LANDING_KEY] is True


def test_a_landed_item_is_no_longer_a_landing_wait(conn):
    """Once the branch is on the base branch the wait is close-out, not GitHub."""
    claim_work(conn, session_id=_session(conn, "sess-landed-item"), item_id=9301)
    conn.execute(
        "UPDATE items SET merge_queue_enqueued_at=%s, merge_queue_landed_at=%s "  # lint:no-lifecycle-mutation-check
        "WHERE id=%s",
        ("2026-09-09T14:00:00Z", "2026-09-09T14:05:00Z", 9301),
    )
    conn.commit()

    assert claimed_item_facts(conn, [9301])[9301][ITEM_AWAITING_LANDING_KEY] is False


def test_an_unarmed_item_is_not_a_landing_wait(conn):
    assert claimed_item_facts(conn, [9301])[9301][ITEM_AWAITING_LANDING_KEY] is False
