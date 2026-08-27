# ruff: noqa: F811
"""The three legs of probing a silent claim-holder: ask, wake, end."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from runtime.api.sessions_api_stale_test_helpers import _ago_minutes
from runtime.api.test_sessions import _insert_claimable_items, _register
from yoke_core.domain.actor_permissions import (
    ROLE_OPERATOR,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.session_stale_alive_probe import (
    PROBE_UNRESPONSIVE_REASON,
    end_probe_unresponsive_sessions,
    probe_key,
    probe_stale_alive_sessions,
)
from yoke_core.domain.sessions import claim_work


MACHINE = "3f2504e0-4f89-41d3-9a0c-0305e82c3401"
OTHER_MACHINE = "3f2504e0-4f89-41d3-9a0c-0305e82c3402"
PROJECTS = (1,)
ITEM_ID = 9401

#: The probe is sent on the authority of whoever owns the session's work,
#: so the session has to carry an actor with a role in its project.
ACTOR_ID = 4401

#: A surface the message router can actually deliver to; without one the
#: probe is refused as unroutable before it is ever sent.
SURFACE = "claude-cli"
SURFACE_VERSION = "2.1.238"

#: ``fleet.stale_alive_probe_seconds`` and ``fleet.wake_ack_grace_seconds``.
PROBE_THRESHOLD = timedelta(seconds=900)
GRACE = timedelta(seconds=300)


@pytest.fixture
def conn(tmp_path):
    """A validation-surface connection carrying BOTH halves this needs.

    The probe reaches across two schemas that no single shared fixture
    spans: session lifecycle and claims on one side, fleet messaging on the
    other. The composed fixture schema builds both, so the only thing left
    here is the organization, project, and actor authority a probe is sent
    under.
    """
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        connection = connect_test_db(db_path)
        try:
            _seed_message_authority(connection)
            yield connection
        finally:
            connection.close()


def _seed_message_authority(conn) -> None:
    conn.execute(
        "INSERT INTO organizations (id, slug, name, created_at) "
        "VALUES (1, 'org', 'Org', %s) ON CONFLICT (id) DO NOTHING",
        (_ago_minutes(0),),
    )
    conn.execute("UPDATE projects SET org_id = 1 WHERE org_id IS NULL")
    conn.execute(
        "INSERT INTO actors (id, kind, created_at) VALUES (%s, 'human', %s) "
        "ON CONFLICT (id) DO NOTHING",
        (ACTOR_ID, _ago_minutes(0)),
    )
    conn.commit()
    seed_roles_and_permissions(conn)
    grant_actor_project_role(
        conn, actor_id=ACTOR_ID, project_id=1, role_name=ROLE_OPERATOR
    )
    conn.commit()


@pytest.fixture(autouse=True)
def _claimable_items(conn):
    _insert_claimable_items(conn, ITEM_ID, ITEM_ID + 1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _quiet_holder(
    conn,
    session_id: str = "sess-quiet",
    *,
    machine_id: str = MACHINE,
    quiet_minutes: int = 180,
    item_id: int = ITEM_ID,
) -> str:
    """Register a claim-holding session that stopped calling tools."""
    _register(
        conn,
        session_id=session_id,
        machine_id=machine_id,
        executor="claude-code",
        actor_id=ACTOR_ID,
    )
    claim_work(conn, session_id=session_id, item_id=item_id)
    old = _ago_minutes(quiet_minutes)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=%s, last_heartbeat=%s, "
        "last_tool_call_at=%s, executor_surface=%s, executor_version=%s "
        "WHERE session_id=%s",
        (machine_id, old, old, SURFACE, SURFACE_VERSION, session_id),
    )
    conn.commit()
    return session_id


def _probe(conn, *, machine_id: str = MACHINE, now: datetime | None = None):
    return probe_stale_alive_sessions(
        conn, machine_id=machine_id, authorized_projects=PROJECTS, now=now
    )


def _end_unanswered(conn, *, machine_id: str = MACHINE, now: datetime | None = None):
    return end_probe_unresponsive_sessions(
        conn, machine_id=machine_id, authorized_projects=PROJECTS, now=now
    )


def _probe_recipient(conn, session_id: str):
    return conn.execute(
        "SELECT r.state, r.wake_attempt_count FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id = r.message_id "
        "WHERE m.idempotency_key = %s",
        (probe_key(session_id),),
    ).fetchone()


def _ended_at(conn, session_id: str):
    return conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()["ended_at"]


def _mark_woken(conn, session_id: str, when: datetime) -> None:
    """Stand in for the wake the sweep fires against a starved probe."""
    conn.execute(
        "UPDATE session_message_recipients SET wake_attempt_count = 1, "
        "last_wake_at = %s WHERE session_id = %s",
        (when.strftime("%Y-%m-%dT%H:%M:%SZ"), session_id),
    )
    conn.commit()


def test_a_parked_quiet_claim_holder_is_not_probed_or_ended(conn):
    session_id = _quiet_holder(conn)
    conn.execute(
        "UPDATE harness_sessions SET mode = %s WHERE session_id = %s",
        ("parked", session_id),
    )
    conn.commit()
    assert _probe(conn) == {"probed": [], "skipped": []}
    assert _probe_recipient(conn, session_id) is None
    assert _end_unanswered(conn) == {"ended": [], "skipped": []}
    assert _ended_at(conn, session_id) is None


def test_a_working_claim_holder_is_never_probed(conn):
    session_id = _quiet_holder(conn, quiet_minutes=0)
    assert _probe(conn) == {"probed": [], "skipped": []}
    assert _probe_recipient(conn, session_id) is None


def test_a_session_stale_but_not_yet_long_enough_is_left_alone(conn):
    # claude-code's stale TTL is 20 minutes, so 25 is stale — but not stale
    # for the further probe threshold this trigger waits out.
    _quiet_holder(conn, quiet_minutes=25)
    assert _probe(conn) == {"probed": [], "skipped": []}


def test_a_session_with_no_claim_is_left_alone(conn):
    _register(conn, session_id="sess-idle", machine_id=MACHINE, actor_id=ACTOR_ID)
    old = _ago_minutes(180)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=%s, last_heartbeat=%s, "
        "last_tool_call_at=%s WHERE session_id=%s",
        (MACHINE, old, old, "sess-idle"),
    )
    conn.commit()
    # Nothing is blocked on a session holding nothing, so nothing is asked.
    assert _probe(conn)["probed"] == []


def test_a_silent_claim_holder_is_probed_once(conn):
    session_id = _quiet_holder(conn)
    assert _probe(conn) == {"probed": [session_id], "skipped": []}
    assert _probe_recipient(conn, session_id)["state"] == "pending"
    # Never two live probes: the next sweep finds the first still pending.
    assert _probe(conn)["probed"] == []


def test_another_machines_session_is_not_this_relays_business(conn):
    _quiet_holder(conn, "sess-elsewhere", machine_id=OTHER_MACHINE)
    assert _probe(conn)["probed"] == []


def test_a_session_that_answers_its_probe_is_never_ended(conn):
    session_id = _quiet_holder(conn)
    assert _probe(conn) == {"probed": [session_id], "skipped": []}
    _mark_woken(conn, session_id, _now() - GRACE - timedelta(seconds=30))
    # Its turn ran again, which is the whole answer the probe was after.
    # The stamp has to be unambiguously after the probe rather than inside
    # the same second, because equal timestamps cannot prove which came
    # first and the sweep will not end a session on an ambiguous answer.
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s WHERE session_id=%s",
        ((_now() + timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ"), session_id),
    )
    conn.commit()

    assert _end_unanswered(conn) == {"ended": [], "skipped": []}
    assert _ended_at(conn, session_id) is None


def test_a_probe_still_inside_its_wake_window_is_not_ended_yet(conn):
    session_id = _quiet_holder(conn)
    _probe(conn)
    _mark_woken(conn, session_id, _now())
    assert _end_unanswered(conn)["ended"] == []
    assert _ended_at(conn, session_id) is None


def test_a_probe_woken_and_still_ignored_ends_the_session_and_frees_its_claims(conn):
    session_id = _quiet_holder(conn)
    assert _probe(conn) == {"probed": [session_id], "skipped": []}
    _mark_woken(conn, session_id, _now() - GRACE - timedelta(seconds=30))

    assert _end_unanswered(conn)["ended"] == [session_id]
    assert _ended_at(conn, session_id) is not None
    held = conn.execute(
        "SELECT COUNT(*) AS cnt FROM work_claims "
        "WHERE session_id = %s AND released_at IS NULL",
        (session_id,),
    ).fetchone()["cnt"]
    # The reason to end here at all is that the claims come back now rather
    # than when the much longer holdings TTL expires.
    assert held == 0


def test_the_end_names_the_probe_and_wake_it_rests_on(conn):
    from yoke_core.domain.sessions_analytics import EVENT_HARNESS_SESSION_ENDED

    session_id = _quiet_holder(conn)
    _probe(conn)
    _mark_woken(conn, session_id, _now() - GRACE - timedelta(seconds=30))
    _end_unanswered(conn)

    envelope = conn.execute(
        "SELECT envelope FROM events WHERE event_name = %s AND session_id = %s "
        "ORDER BY id DESC LIMIT 1",
        (EVENT_HARNESS_SESSION_ENDED, session_id),
    ).fetchone()["envelope"]
    # A verdict an operator cannot question is not evidence.
    assert PROBE_UNRESPONSIVE_REASON in str(envelope)
    assert "stale_alive_probe" in str(envelope)
