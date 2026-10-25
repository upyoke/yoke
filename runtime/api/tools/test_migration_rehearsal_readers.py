"""Migrated storage is not proof that the product can decode it."""

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from runtime.api.fixtures.session_holdings import insert_session
from yoke_core.tools import migration_rehearsal_readers as readers
from yoke_core.domain import db_backend


def test_reader_refusal_is_failure_with_operation_and_recovery():
    try:
        readers.checked(
            "sessions.list",
            lambda _: HandlerOutcome(
                primary_success=False,
                error=FunctionError(code="payload_invalid", message="invalid_instant"),
            ),
        )
    except RuntimeError as exc:
        assert "sessions.list: payload_invalid: invalid_instant" in str(exc)
    else:
        raise AssertionError("a refused decode cannot pass rehearsal")


def test_all_real_readers_run_on_disposable_database(test_db):
    assert readers.verify_migrated_readers(test_db, db_backend.resolve_pg_dsn()) is None


def test_session_decode_outside_list_window_is_not_hidden(test_db, monkeypatch):
    insert_session(test_db, "old-session")
    original = readers.sessions_list.handle_sessions_list
    seen = []

    def read(request):
        seen.append(request.payload.get("session_id"))
        if request.payload.get("session_id") == "old-session":
            raise ValueError("invalid_instant: numeric diagnostic clock")
        return original(request)

    monkeypatch.setattr(readers.sessions_list, "handle_sessions_list", read)
    detail = readers.verify_migrated_readers(test_db, db_backend.resolve_pg_dsn())
    assert None in seen and "old-session" in seen
    assert "sessions.list: ValueError: invalid_instant" in detail


def test_failed_reader_prevents_release_tooling(monkeypatch):
    from yoke_core.tools import yoke_migration_rehearsal as fleet

    monkeypatch.setattr(
        readers, "verify_migrated_readers", lambda *_: "launch decode failed"
    )
    monkeypatch.setattr(
        fleet,
        "verify_migrated_release_surfaces",
        lambda *_: (_ for _ in ()).throw(AssertionError("unreachable")),
    )
    assert fleet.verify_migrated_copy(None, "copy") == "launch decode failed"


def test_numeric_diagnostic_expiry_in_stored_attempt_fails_real_reader(test_db):
    import json
    from yoke_core.domain.actors import seed_human_actor
    from yoke_contracts.timestamps import utc_now

    actor = seed_human_actor(test_db, "Rehearsal fixture")
    insert_session(test_db, "diagnostic-session")
    stamp = utc_now()
    test_db.execute(
        "INSERT INTO session_messages(message_id,sender_actor_id,body,body_sha256,"
        "selector_snapshot,created_at,expires_at) VALUES ('diagnostic-message',%s,'fixture','digest','{}',%s,%s)",
        (actor, stamp, stamp),
    )
    test_db.execute(
        "INSERT INTO session_message_recipients(message_id,session_id,project_id,"
        "resolution_evidence,routing_snapshot,created_at,wake_after) "
        "VALUES ('diagnostic-message','diagnostic-session',1,'{}','{}',%s,%s)",
        (stamp, stamp),
    )
    test_db.execute(
        "INSERT INTO session_message_attempts(attempt_id,message_id,target_session_id,"
        "attempt_kind,started_at,evidence) VALUES ('diagnostic-attempt','diagnostic-message',"
        "'diagnostic-session','hook',%s,%s)",
        (stamp, json.dumps({"diagnostic_expires_at": 1791748800})),
    )
    test_db.commit()
    detail = readers.verify_migrated_readers(test_db, db_backend.resolve_pg_dsn())
    assert detail is not None
    assert "InvalidInstant" in detail and "RFC3339" in detail
    assert any(
        surface in detail
        for surface in (
            "sessions.list",
            "frontier.list",
            "board.data.get",
            "messages.get attempts",
        )
    )
