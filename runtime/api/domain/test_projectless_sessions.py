"""Machine-scoped sessions retain delivery and lifecycle authority."""

from datetime import timedelta

import pytest

from runtime.api.domain.test_session_registration_scope import register, world as world
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import sessions_cleanup as cleanup
from yoke_core.domain.scratch_auto_prune import ScratchPruneResult
from yoke_core.domain.sessions_render_end_if_empty import end_session_if_empty


def _message(w, *, last_wake=None):
    now = utc_now()
    w.conn.execute(
        "INSERT INTO session_messages(message_id,sender_actor_id,body,body_sha256,"
        "selector_snapshot,created_at,expires_at) VALUES "
        "('delivery',%s,'work','digest','{}',%s,%s)",
        (w.owner, now, now + timedelta(hours=1)),
    )
    w.conn.execute(
        "INSERT INTO session_message_recipients(message_id,session_id,org_id,"
        "resolution_evidence,routing_snapshot,created_at,wake_after,last_wake_at) "
        "VALUES ('delivery','registration',%s,'{}','{}',%s,%s,%s)",
        (w.org, now, now, last_wake),
    )
    w.conn.commit()


def _stale(w, monkeypatch):
    register(w)
    old = utc_now() - timedelta(days=7)
    w.conn.execute(
        "UPDATE harness_sessions SET offered_at=%s,last_heartbeat=%s,"
        "last_tool_call_at=%s,episode_started_at=%s WHERE session_id='registration'",
        (old, old, old, old),
    )
    w.conn.commit()
    monkeypatch.setattr(
        cleanup, "auto_prune_stale_scratch", lambda conn: ScratchPruneResult()
    )


def test_project_filtered_cleanup_skips_org_rows(world, monkeypatch):
    _stale(world, monkeypatch)
    result = cleanup.clean_stale_harness_sessions(world.conn, project_ids=[1])
    assert result["total_reclaimed"] == result["org_scoped_reclaimed"] == 0
    assert (
        world.conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='registration'"
        ).fetchone()[0]
        is None
    )


def test_universe_cleanup_reaps_org_rows_releases_holds(world, monkeypatch):
    from runtime.api.domain.steering_claim_test_support import seed_strategy_doc
    from yoke_core.domain.strategy_doc_session_claims import acquire_session_doc_claim

    _stale(world, monkeypatch)
    seed_strategy_doc(world.conn, 1, "LIFECYCLE-PLAN")
    acquire_session_doc_claim(
        world.conn,
        project_id=1,
        slug="LIFECYCLE-PLAN",
        session_id="registration",
        actor_id=world.owner,
    )
    _message(world)
    result = cleanup.clean_stale_harness_sessions(world.conn)
    assert result["total_reclaimed"] == result["org_scoped_reclaimed"] == 1
    assert (
        world.conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='registration'"
        ).fetchone()[0]
        is not None
    )
    assert (
        world.conn.execute(
            "SELECT released_at FROM strategy_doc_claims "
            "WHERE owner_session_id='registration'"
        ).fetchone()[0]
        is not None
    )
    assert (
        world.conn.execute(
            "SELECT state FROM session_message_recipients WHERE message_id='delivery'"
        ).fetchone()[0]
        == "cancelled"
    )


@pytest.mark.parametrize("wake", [False, True])
def test_end_if_empty_blocked_by_pending_and_holds(world, wake):
    register(world)
    _message(world, last_wake=utc_now() if wake else None)
    result = end_session_if_empty(world.conn, "registration")
    assert not result["ended"]
    assert result["status"] == (
        "wake_delivery_in_flight" if wake else "has_pending_messages"
    )


def test_concurrent_reap_and_hook_no_premature_end(world, monkeypatch):
    from runtime.api.fixtures.session_holdings import insert_steering_claim

    _stale(world, monkeypatch)
    original = cleanup.reclaim_facts

    def acquired_before_recheck(conn, rows):
        insert_steering_claim(conn, "registration", project_id=1)
        return original(conn, rows)

    monkeypatch.setattr(cleanup, "reclaim_facts", acquired_before_recheck)
    assert cleanup.clean_stale_harness_sessions(world.conn)["total_reclaimed"] == 0
    assert not end_session_if_empty(world.conn, "registration")["ended"]
