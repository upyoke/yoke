"""Prune and message writers share real Postgres rows without lock waits."""

from datetime import timedelta

from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.fixtures.session_holdings import insert_session
from yoke_contracts.timestamps import utc_now
from yoke_contracts.universe_retention import PruneRequest
from yoke_core.domain import session_message_delivery as delivery
from yoke_core.domain.actor_message_recipients import expire_due_actor_recipients
from yoke_core.domain.universe_retention_pass import prune_pass


def _message(conn, message_id, *, created_at, expires_at, state, acknowledged_at):
    conn.execute(
        "INSERT INTO session_messages (message_id,sender_session_id,body,body_sha256,selector_snapshot,created_at,expires_at,sender_surface) "
        "VALUES (%s,'sender','body','digest','{}',%s,%s,'harness_session')",
        (message_id, created_at, expires_at),
    )
    conn.execute(
        "INSERT INTO session_message_recipients (message_id,session_id,project_id,resolution_evidence,routing_snapshot,state,created_at,wake_after,acknowledged_at) "
        "VALUES (%s,'recipient',1,'{}','{}',%s,%s,%s,%s)",
        (message_id, state, created_at, created_at, acknowledged_at),
    )


def test_prune_and_message_expiry_do_not_deadlock(test_db):
    now = utc_now()
    old = now - timedelta(days=500)
    insert_session(test_db, "sender", ended_at=old)
    insert_session(test_db, "recipient", ended_at=old)
    human = test_db.execute(
        "SELECT id FROM actors WHERE kind='human' LIMIT 1"
    ).fetchone()[0]
    _message(
        test_db,
        "settled",
        created_at=old,
        expires_at=old,
        state="acknowledged",
        acknowledged_at=old,
    )
    _message(
        test_db,
        "due",
        created_at=now - timedelta(hours=1),
        expires_at=now - timedelta(minutes=1),
        state="pending",
        acknowledged_at=None,
    )
    test_db.execute(
        "INSERT INTO actor_message_recipients (message_id,actor_id,state,created_at) "
        "VALUES ('due',%s,'pending',%s)",
        (human, now),
    )
    test_db.commit()
    with connect_test_database(test_db.info.dbname) as expiry:
        expiry.execute("SET lock_timeout='2s'")
        # Relay expiry order: session receipts first (held open here)...
        assert delivery._expire_rows(expiry, now=now) == 1
        # ...while a full prune run deletes settled graphs without waiting.
        request = PruneRequest(apply=True)
        while True:
            result = prune_pass(test_db, request)
            assert result["failure"] is None and result["skipped"] == [], result
            if result["cycle_complete"]:
                break
            request = PruneRequest(
                apply=True,
                cutoff=result["cutoff"],
                expected_digest=result["policy_digest"],
                table_index=result["next_table_index"],
            )
        # ...then actor receipts, which prune no longer holds table-wide.
        assert expire_due_actor_recipients(expiry, now=now) == 1
        expiry.commit()
    messages = {
        r[0] for r in test_db.execute("SELECT message_id FROM session_messages")
    }
    assert messages == {"due"}
    assert test_db.execute(
        "SELECT state FROM session_message_recipients WHERE message_id='due'"
    ).fetchone() == ("expired",)
