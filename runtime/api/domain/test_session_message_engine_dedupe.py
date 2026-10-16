"""Engine-sent messages carry no sender actor yet still dedupe by key."""

from datetime import timedelta

import psycopg
import pytest

from yoke_core.domain.session_message_store import insert_message
from runtime.api.domain.test_session_message_support import NOW


def _engine_notice(conn, key):
    return insert_message(
        conn,
        sender_actor_id=None,
        sender_session_id=None,
        sender_surface=None,
        body="engine notice",
        selector_snapshot={},
        idempotency_key=key,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        recipients=[],
        actor_recipients=[],
        wake_after_by_owner={},
    )


def test_a_repeated_engine_notice_returns_the_original(test_db):
    first, inserted = _engine_notice(test_db, "engine-notice:1")
    again, reinserted = _engine_notice(test_db, "engine-notice:1")
    assert inserted and not reinserted
    assert again["message_id"] == first["message_id"]
    assert again["sender_actor_id"] is None
    count = test_db.execute(
        "SELECT count(*) FROM session_messages WHERE idempotency_key = %s",
        ("engine-notice:1",),
    ).fetchone()[0]
    assert count == 1


def test_the_engine_dedupe_index_refuses_a_second_unattributed_row(test_db):
    first, _ = _engine_notice(test_db, "engine-notice:2")
    row = test_db.execute(
        "SELECT body, body_sha256, selector_snapshot, created_at, expires_at "
        "FROM session_messages WHERE message_id = %s",
        (first["message_id"],),
    ).fetchone()
    with pytest.raises(psycopg.errors.UniqueViolation, match="engine_dedupe"):
        test_db.execute(
            "INSERT INTO session_messages (message_id, sender_actor_id, body, "
            "body_sha256, selector_snapshot, idempotency_key, created_at, expires_at) "
            "VALUES ('duplicate-engine-notice', NULL, %s, %s, %s, %s, %s, %s)",
            (row[0], row[1], row[2], "engine-notice:2", row[3], row[4]),
        )
