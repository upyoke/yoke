"""Copy batches retain canonical reads, malformed-row failures and isolation."""

import sqlite3

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.session_holdings import insert_session
from runtime.api.domain.session_launch_test_support import (
    add_relay,
    assigned_launch,
    launch_connection,
)
from yoke_contracts.items_projection import DEFAULT_GET_FIELDS
from yoke_core.domain import db_backend, items_queries, sessions_list_read
from yoke_core.domain.session_launch_store import get_launch, launch_read_batch
from yoke_core.domain.session_launch_projection import public_launch_record
from yoke_core.domain.session_message_attempt_reads import (
    message_attempt_evidence,
    message_attempt_read_batch,
)


def test_session_batch_keeps_full_projection_and_physically_closes(
    test_db, monkeypatch
):
    for key in ("batch-a", "batch-b"):
        insert_session(test_db, key)
    dsn = db_backend.resolve_pg_dsn()
    with db_backend.bound_pg_dsn(dsn):
        expected = {
            key: sessions_list_read.list_sessions(session_id=key)
            for key in ("batch-a", "batch-b")
        }
        original = sessions_list_read.db_helpers.connect
        opened = []

        def connect():
            conn = original()
            opened.append(conn)
            return conn

        monkeypatch.setattr(sessions_list_read.db_helpers, "connect", connect)
        with sessions_list_read.session_read_batch(["batch-a", "batch-b"]):
            for key in expected:
                assert sessions_list_read.list_sessions(session_id=key) == expected[key]
            assert len(opened) == 1
            assert opened[0].closed
            with pytest.raises(ValueError, match="nonnegative"):
                sessions_list_read.list_sessions(session_id="batch-a", offset=-1)
        sessions_list_read.list_sessions(session_id="batch-a")
        assert len(opened) == 2 and opened[1].closed


def test_item_batch_keeps_every_default_field_and_discards_on_exit(
    test_db, monkeypatch
):
    insert_item(test_db, id=801, title="First", spec="Full spec", frozen=1)
    insert_item(test_db, id=802, title="Second")
    test_db.commit()
    fields = [
        field
        for field in DEFAULT_GET_FIELDS
        if field not in {"id", "deployment_flow", "post_deploy_qa"}
    ]
    with db_backend.bound_pg_dsn(db_backend.resolve_pg_dsn()):
        expected = {
            (key, field): items_queries.query_item(key, field)
            for key in (801, 802)
            for field in fields
        }
        with items_queries.item_field_read_batch(
            test_db, [801, 802], DEFAULT_GET_FIELDS
        ):

            def unreachable(*args):
                raise AssertionError("a cached field opened a connection")

            with monkeypatch.context() as patch:
                patch.setattr(items_queries, "connect", unreachable)
                assert {
                    (key, field): items_queries.query_item(key, field)
                    for key in (801, 802)
                    for field in fields
                } == expected
                with db_backend.bound_pg_dsn("different-copy-authority"):
                    with pytest.raises(AssertionError, match="opened a connection"):
                        items_queries.query_item(801, "title")
        test_db.execute("UPDATE items SET title='Changed' WHERE id=801")
        test_db.commit()
        assert items_queries.query_item(801, "title") == "Changed"


def test_launch_batch_keeps_decoder_and_projection():
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, key="batch-launch")
    expected = public_launch_record(get_launch(conn, launch.launch_id))
    statements = []
    conn.set_trace_callback(statements.append)
    with launch_read_batch(conn, [launch.launch_id]):
        statements.clear()
        assert public_launch_record(get_launch(conn, launch.launch_id)) == expected
        assert statements == []
    conn.execute(
        "UPDATE session_launches SET created_at=17 WHERE launch_id=?",
        (launch.launch_id,),
    )
    with launch_read_batch(conn, [launch.launch_id]):
        with pytest.raises(ValueError):
            get_launch(conn, launch.launch_id)
    conn.close()


def test_attempt_batch_preserves_count_window_order_and_decode_failure():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session_message_attempts (attempt_id TEXT,message_id TEXT,"
        "target_session_id TEXT,broker_session_id TEXT,attempt_kind TEXT,"
        "adapter_revision TEXT,started_at TEXT,completed_at TEXT,result_code TEXT,evidence TEXT)"
    )
    conn.executemany(
        "INSERT INTO session_message_attempts VALUES (?,'m','s',NULL,'hook',NULL,"
        "'2026-10-15T12:00:00Z',NULL,NULL,'{}')",
        [(f"a-{n:04d}",) for n in range(502)],
    )
    expected = message_attempt_evidence(conn, "m")
    assert expected["attempt_count"] == 502 and expected["attempts_truncated"]
    statements = []
    conn.set_trace_callback(statements.append)
    with message_attempt_read_batch(conn, ["m", "empty"]):
        statements.clear()
        assert message_attempt_evidence(conn, "m") == expected
        assert message_attempt_evidence(conn, "empty")["attempt_count"] == 0
        assert statements == []
    conn.execute(
        "UPDATE session_message_attempts SET evidence=? WHERE attempt_id='a-0000'",
        ('{"diagnostic_expires_at":17}',),
    )
    with message_attempt_read_batch(conn, ["m"]):
        with pytest.raises(ValueError):
            message_attempt_evidence(conn, "m")
    conn.close()
