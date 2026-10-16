"""Focused command, protection, interruption and settings regression cases."""

from contextlib import contextmanager
from datetime import timedelta
import json
import time

import pytest

from runtime.api.fixtures.backlog import insert_event, insert_item, insert_item_worktree
from runtime.api.fixtures.session_holdings import insert_session
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_contracts.timestamps import utc_now
from yoke_contracts.universe_retention import PruneRequest, RetentionPolicy
from yoke_core.domain import db_helpers, universe_retention as retention
from yoke_core.domain.handlers import universe_retention as handlers
from yoke_cli.commands.adapters import universe_retention as cli


def _cli_on(conn, monkeypatch):
    @contextmanager
    def connect(*_args, **_kwargs):
        yield conn

    monkeypatch.setattr(db_helpers, "connect", connect)
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)

    def call(**kwargs):
        request = FunctionCallRequest(
            function=kwargs["function_id"],
            target=kwargs["target"],
            actor=kwargs["actor"],
            payload=kwargs["payload"],
        )
        outcome = handlers.handle_prune(request)
        return FunctionCallResponse(
            success=outcome.primary_success,
            function=request.function,
            version="v1",
            request_id=request.request_id,
            result=outcome.result_payload,
            error=outcome.error,
        )

    monkeypatch.setattr(cli, "call_dispatcher", call)


def test_command_preview_apply_rerun_and_seed_preserve_data(
    test_db, monkeypatch, capsys
):
    now = utc_now()
    _cli_on(test_db, monkeypatch)
    test_db.execute("DELETE FROM universe_settings WHERE key='retention'")
    test_db.commit()
    assert retention.read_policy(test_db)[1] == "default"
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM universe_settings WHERE key='retention'"
        ).fetchone()[0]
        == 0
    )
    retention.seed_defaults(test_db)
    policy = RetentionPolicy(batch_rows=3)
    test_db.execute(
        "UPDATE universe_settings SET value=%s WHERE key='retention'",
        (policy.model_dump_json(),),
    )
    retention.seed_defaults(test_db)
    test_db.commit()
    assert retention.read_policy(test_db)[0].batch_rows == 3
    for index in range(5):
        insert_event(
            test_db,
            event_id=f"expired-{index}",
            severity="DEBUG",
            created_at=now - timedelta(days=2),
        )
    insert_event(test_db, event_id="recent", severity="DEBUG", created_at=now)
    insert_event(
        test_db,
        event_id="old-error",
        severity="ERROR",
        created_at=now - timedelta(days=181),
    )
    insert_event(
        test_db,
        event_id="override",
        event_name="YokeFunctionCalled",
        severity="INFO",
        created_at=now - timedelta(days=8),
    )
    test_db.commit()
    before = test_db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert cli.universe_prune(["--dry-run", "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    events = next(r for r in preview["result"]["tables"] if r["table"] == "events")
    assert events["eligible"] == 3 and events["eligible_partial"]
    assert test_db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before
    assert cli.universe_prune(["--apply", "--json"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["result"]["deleted"]["events"] == 7
    assert test_db.execute(
        "SELECT event_id FROM events WHERE event_id='recent'"
    ).fetchone()
    assert cli.universe_prune(["--apply", "--json"]) == 0
    assert sum(json.loads(capsys.readouterr().out)["result"]["deleted"].values()) == 0
    with pytest.raises(ValueError, match="retention_policy_changed"):
        retention.prune_pass(test_db, PruneRequest(expected_digest="wrong"))
    with pytest.raises(ValueError, match="seven-day"):
        RetentionPolicy(windows={**policy.windows, "replay": 1})


def _target(conn, path, generation=1):
    return conn.execute(
        "INSERT INTO path_targets (project_id,kind,path_string,generation,created_at) "
        "VALUES (1,'file',%s,%s,%s) RETURNING id",
        (path, generation, utc_now()),
    ).fetchone()[0]


def test_human_live_reference_snapshot_and_upload_protections(test_db):
    from yoke_core.domain.project_snapshot_sync_refusals import ChunkUploadMissingError
    from yoke_core.domain.retention_operational_policy import require_fresh_upload

    old = utc_now() - timedelta(days=500)
    insert_session(test_db, "sender", ended_at=old)
    insert_session(test_db, "recipient", ended_at=old)
    human = test_db.execute(
        "SELECT id FROM actors WHERE kind='human' LIMIT 1"
    ).fetchone()[0]
    for message, origin in (
        ("agent", "harness_session"),
        ("human", "cli"),
        ("received", "harness_session"),
        ("unknown", None),
        ("pending", "harness_session"),
    ):
        test_db.execute(
            "INSERT INTO session_messages (message_id,sender_session_id,body,body_sha256,selector_snapshot,created_at,expires_at,sender_surface) "
            "VALUES (%s,'sender','body','digest','{}',%s,%s,%s)",
            (message, old, old, origin),
        )
        test_db.execute(
            "INSERT INTO session_message_recipients (message_id,session_id,project_id,resolution_evidence,routing_snapshot,state,created_at,wake_after,acknowledged_at) "
            "VALUES (%s,'recipient',1,'{}','{}',%s,%s,%s,%s)",
            (
                message,
                "pending" if message == "pending" else "acknowledged",
                old,
                old,
                None if message == "pending" else old,
            ),
        )
    test_db.execute(
        "INSERT INTO actor_message_recipients (message_id,actor_id,state,created_at,read_at) VALUES ('received',%s,'read',%s,%s)",
        (human, old, old),
    )
    main, gone = _target(test_db, "current.py"), _target(test_db, "gone.py")
    snapshots = []
    for index in range(6):
        snap = test_db.execute(
            "INSERT INTO path_snapshots (project_id,commit_sha,built_at) VALUES (1,%s,%s) RETURNING id",
            (str(index) * 40, old),
        ).fetchone()[0]
        snapshots.append(snap)
        if index < 5:
            test_db.execute(
                "INSERT INTO path_snapshot_entries (snapshot_id,target_id) VALUES (%s,%s)",
                (snap, main),
            )
    test_db.execute(
        "INSERT INTO path_snapshot_entries (snapshot_id,target_id) VALUES (%s,%s)",
        (snapshots[0], gone),
    )
    test_db.execute(
        "INSERT INTO path_targets (project_id,kind,path_string,generation,created_at) "
        "SELECT 1,'file','bulk/'||n,1,%s FROM generate_series(1,5001) n",
        (old,),
    )
    for snap in snapshots[2:5]:
        test_db.execute(
            "INSERT INTO path_snapshot_entries (snapshot_id,target_id) "
            "SELECT %s,id FROM path_targets WHERE path_string LIKE 'bulk/%%'",
            (snap,),
        )
    for snap, generation in ((snapshots[2], 1), (snapshots[4], 2)):
        test_db.execute(
            "INSERT INTO path_snapshot_entries (snapshot_id,target_id) VALUES (%s,%s)",
            (snap, _target(test_db, "changing.py", generation)),
        )
    insert_item(test_db)
    insert_item_worktree(test_db, item_id=1, branch="active")
    test_db.execute("UPDATE item_worktrees SET commit_sha=%s", ("1" * 40,))
    insert_event(test_db, event_id="pinned", severity="INFO", created_at=old)
    test_db.execute(
        "INSERT INTO path_moves (before_target_id,after_target_id,recorded_event_id,recorded_at) VALUES (%s,%s,'pinned',%s)",
        (main, main, old),
    )
    # A nullable reference must neither suppress eligible events nor unpin one.
    insert_event(test_db, event_id="unreferenced", severity="INFO", created_at=old)
    test_db.execute(
        "WITH run AS (INSERT INTO path_integrity_runs (status,started_at) "
        "VALUES ('completed',%s) RETURNING id), "
        "failure AS (INSERT INTO path_integrity_failures (run_id,invariant_kind,recorded_at) "
        "SELECT id,'missing',%s FROM run RETURNING id) "
        "INSERT INTO path_integrity_repairs (failure_id,operation,status,requested_at,recorded_event_id) "
        "SELECT id,'repair','failed',%s,NULL FROM failure",
        (old, old, old),
    )
    test_db.execute(
        "INSERT INTO path_snapshot_sync_uploads (upload_id,project_ref,ref,commit_sha,expected_file_count,expected_chunk_count,warnings_json,symlinks_json,created_at) "
        "VALUES ('expired','yoke','main',%s,1,1,'[]','[]',%s)",
        ("a" * 40, old),
    )
    test_db.execute(
        "INSERT INTO path_snapshot_sync_upload_chunks VALUES ('expired',0,'[]')"
    )
    test_db.execute(
        "INSERT INTO session_tool_calls (session_id,tool_use_id,started_at) VALUES ('sender','unresolved',%s)",
        (old,),
    )
    test_db.commit()
    with pytest.raises(ChunkUploadMissingError, match="restart"):
        require_fresh_upload(test_db, "expired")
    test_db.rollback()
    from yoke_core.domain.universe_retention_snapshots import snapshot_policy

    first = retention._table_pass(
        test_db, RetentionPolicy(), time.monotonic() + 20, snapshot_policy(), True
    )
    assert first["deleted"] == {
        "path_snapshot_entries": 5003,
        "path_snapshot_symlink_facts": 0,
        "path_snapshots": 1,
    }
    assert first["eligible_partial"] and first["protected_graphs"] == 0
    assert not test_db.execute(
        "SELECT 1 FROM path_snapshots WHERE id=%s", (snapshots[2],)
    ).fetchone()
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM path_snapshot_entries WHERE snapshot_id=%s",
            (snapshots[3],),
        ).fetchone()[0]
        == 5002
    )
    test_db.commit()
    request = PruneRequest(apply=True)
    while True:
        result = retention.prune_pass(test_db, request)
        assert result["failure"] is None, result
        if result["cycle_complete"]:
            break
        request = PruneRequest(
            apply=True,
            cutoff=result["cutoff"],
            expected_digest=result["policy_digest"],
            table_index=result["next_table_index"],
        )
    assert {
        r[0] for r in test_db.execute("SELECT message_id FROM session_messages")
    } == {"human", "received", "unknown", "pending"}
    assert test_db.execute(
        "SELECT event_id FROM events WHERE event_id IN ('pinned','unreferenced')"
    ).fetchall() == [("pinned",)]
    assert {r[0] for r in test_db.execute("SELECT id FROM path_snapshots")} == {
        snapshots[index] for index in (0, 1, 4, 5)
    }
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM path_snapshot_sync_upload_chunks"
        ).fetchone()[0]
        == 0
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM session_tool_calls WHERE tool_use_id='unresolved'"
        ).fetchone()[0]
        == 1
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM events WHERE event_id='pinned'"
        ).fetchone()[0]
        == 1
    )
    import psycopg
    from yoke_core.domain.path_snapshot_content_rows import find_content_snapshot_id

    assert find_content_snapshot_id(test_db, 1, "4" * 40) == snapshots[4]
    from runtime.api.fixtures.pg_testdb import connect_test_database

    with connect_test_database(test_db.info.dbname) as other:
        with pytest.raises(psycopg.errors.LockNotAvailable):
            other.execute("LOCK TABLE path_snapshots IN ACCESS EXCLUSIVE MODE NOWAIT")
        other.rollback()
        test_db.commit()
        other.execute("LOCK TABLE path_snapshots IN ACCESS EXCLUSIVE MODE NOWAIT")


def test_command_lost_reply_keeps_acknowledged_counts_and_does_not_retry(
    monkeypatch, capsys
):
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)
    calls = []

    def call(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return FunctionCallResponse(
                success=True,
                function="universe.prune.run",
                version="v1",
                result={
                    "universe": {"slug": "example"},
                    "source": "default",
                    "policy": {},
                    "policy_digest": "digest",
                    "cutoff": utc_now().isoformat(),
                    "next_table_index": 1,
                    "cycle_complete": False,
                    "tables": [
                        {
                            "table": "events",
                            "deleted": {"events": 5},
                            "eligible": 5,
                            "eligible_partial": True,
                            "protected": 0,
                        }
                    ],
                },
            )
        return FunctionCallResponse(
            success=False,
            function="universe.prune.run",
            version="v1",
            error=FunctionError(code=cli.TRANSPORT_FAILED_CODE, message="lost reply"),
        )

    monkeypatch.setattr(cli, "call_dispatcher", call)
    assert cli.universe_prune(["--apply", "--json"]) != 0
    result = json.loads(capsys.readouterr().out)
    assert result["result"]["deleted"] == {"events": 5}
    assert result["error"]["code"] == "retention_pass_outcome_unknown"
    assert len(calls) == 2 and all(c["max_attempts"] == 1 for c in calls)
