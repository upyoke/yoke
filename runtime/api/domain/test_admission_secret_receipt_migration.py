"""Historical token receipts are scrubbed without changing replay identity."""

from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3

import pytest

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain import events, function_call_ledger as ledger
from yoke_core.domain.admission_result_redaction import ONE_TIME_SECRET_GUARDRAIL
from yoke_core.domain.events_insert_sql import _INSERT_SQL
from yoke_core.domain.events_write_conn import event_insert_params, write_event_row_on_conn
from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum
from yoke_core.domain.yoke_function_idempotency_scope import idempotency_payload_checksum


ENTRY_NAME = "0079_scrub_admission_secret_receipts"
FUNCTION = "profile.token.create"
SECRET = "yk_fixture_only_one_time_token"
REDACTED = {"result_redacted": ONE_TIME_SECRET_GUARDRAIL}
STAMP = "2026-01-02T03:04:05.000000Z"


def _entry():
    return importlib.import_module(f"yoke_core.domain.migrations.{ENTRY_NAME}")


def _request_checksum():
    request = FunctionCallRequest(
        function=FUNCTION, actor={"session_id": "receipt-session"},
        target={"kind": "global"}, payload={"name": "automation"},
        preconditions={"expected_version": 1}, request_id="secret-receipt",
    )
    canonical_request = json.dumps({
        "version": request.version,
        "target": request.target.model_dump(exclude_none=True),
        "payload": dict(request.payload),
        "preconditions": dict(request.preconditions),
        "intent": request.intent,
    }, sort_keys=True, separators=(",", ":"))
    checksum = idempotency_payload_checksum(request)
    assert checksum == hashlib.sha256(canonical_request.encode()).hexdigest()
    return checksum


def _ledger_row(conn, request_id, result, *, function=FUNCTION):
    ledger.record_call(
        request_id, function, result, actor_id="receipt-actor",
        authorization_scope="project:1", payload_checksum=_request_checksum(),
        created_at=STAMP, conn=conn,
    )


def _event_row(conn, result, *, function=FUNCTION, name="YokeFunctionCalled"):
    envelope = events.build_envelope(
        name, event_kind="domain", event_type="function", source_type="backend",
        session_id="receipt-session", request_id="secret-receipt", created_at=STAMP,
        context={"function": function, "result": result, "payload_checksum": "request-hash",
                 "result_checksum": "original-result-hash", "detail": "preserve\x00this"},
    )
    params = event_insert_params(envelope, None)
    write_event_row_on_conn(conn, _INSERT_SQL, params)
    return envelope


def _snapshot(conn, table):
    cursor = conn.execute(f"SELECT * FROM {table}")
    columns = [description[0] for description in cursor.description]
    return {row[0]: dict(zip(columns, row)) for row in cursor.fetchall()}


def test_floor_and_born_universe_are_safe(test_db, capsys):
    assert declared_minimum(_entry()) == NEXT_RELEASE
    assert test_db.execute(
        "SELECT 1 FROM applied_migrations WHERE migration_name = %s", (ENTRY_NAME,),
    ).fetchone()
    capsys.readouterr()
    _entry().apply(test_db)
    _entry().invariants(test_db)
    assert capsys.readouterr().out == (
        "admission_secret_receipts ledger_rows_rewritten=0 event_envelopes_rewritten=0\n"
    )


def test_existing_receipts_preserve_identity_bytes_and_request_checksum(
    test_db, capsys, caplog,
):
    _ledger_row(test_db, "secret-receipt", {"raw_token": SECRET, "token_id": 41})
    envelope = _event_row(test_db, {"raw_token": SECRET, "token_id": 41})
    # Adjacent results stay byte-identical, even if they mention a raw token.
    for request_id, function, raw in (
        ("other-function", "profile.token.list", '{ "raw_token" : "other" }'),
        ("already-redacted", FUNCTION, ledger.serialize_result(REDACTED)),
        ("nested-field", FUNCTION, '{ "detail": {"raw_token": "nested"} }'),
        ("invalid-json", FUNCTION, '{ "raw_token":'),
        ("list-result", FUNCTION, ' [ {"raw_token": "nested"} ] '),
        ("null-result", FUNCTION, "null"),
        ("absent-result", FUNCTION, None),
    ):
        _ledger_row(test_db, request_id, {}, function=function)
        test_db.execute(
            "UPDATE function_call_ledger SET result = %s WHERE request_id = %s",
            (raw, request_id),
        )
    _event_row(test_db, {"raw_token": SECRET}, function="profile.token.list")
    _event_row(test_db, {"raw_token": SECRET}, name="UnrelatedEvent")
    _event_row(test_db, REDACTED)
    _event_row(test_db, [SECRET])
    for raw in (' {"context": null} ', ' ["context"] '):
        untouched = _event_row(test_db, {})
        test_db.execute(
            "UPDATE events SET envelope = %s WHERE event_id = %s",
            (raw, untouched["event_id"]),
        )
    before_ledger = _snapshot(test_db, "function_call_ledger")
    before_events = _snapshot(test_db, "events")
    capsys.readouterr()

    with pytest.raises(AssertionError, match="ledger_rows=1, event_envelopes=1") as error:
        _entry().invariants(test_db)
    assert SECRET not in str(error.value)
    _entry().apply(test_db)
    _entry().invariants(test_db)

    before_ledger["secret-receipt"]["result"] = ledger.serialize_result(REDACTED)
    envelope["context"]["result"] = REDACTED
    expected_event_bytes = event_insert_params(envelope, None)[-2]
    affected_event = next(
        row for row in before_events.values() if row["event_id"] == envelope["event_id"]
    )
    affected_event["envelope"] = expected_event_bytes
    assert _snapshot(test_db, "function_call_ledger") == before_ledger
    assert _snapshot(test_db, "events") == before_events
    receipt = before_ledger["secret-receipt"]
    assert receipt["payload_checksum"] == _request_checksum()
    assert receipt["payload_checksum"] != hashlib.sha256(receipt["result"].encode()).hexdigest()
    assert capsys.readouterr().out == (
        "admission_secret_receipts ledger_rows_rewritten=1 event_envelopes_rewritten=1\n"
    )

    _entry().apply(test_db)
    _entry().invariants(test_db)
    assert _snapshot(test_db, "function_call_ledger") == before_ledger
    assert _snapshot(test_db, "events") == before_events
    output = capsys.readouterr()
    assert output.out == (
        "admission_secret_receipts ledger_rows_rewritten=0 event_envelopes_rewritten=0\n"
    )
    assert SECRET not in output.out + output.err + caplog.text


@pytest.mark.parametrize("table", (None, "function_call_ledger", "events"))
def test_absent_tables_and_caller_rollback(table, capsys):
    conn = sqlite3.connect(":memory:")
    try:
        if table == "function_call_ledger":
            conn.execute(
                "CREATE TABLE function_call_ledger (request_id TEXT, function_id TEXT, result TEXT)"
            )
            conn.execute(
                "INSERT INTO function_call_ledger VALUES (?, ?, ?)",
                ("receipt", FUNCTION, ledger.serialize_result({"raw_token": SECRET})),
            )
        elif table == "events":
            conn.execute("CREATE TABLE events (id INTEGER, event_name TEXT, envelope TEXT)")
            conn.execute(
                "INSERT INTO events VALUES (?, ?, ?)",
                (1, "YokeFunctionCalled", json.dumps({"context": {
                    "function": FUNCTION, "result": {"raw_token": SECRET},
                }})),
            )
            conn.execute(
                "INSERT INTO events VALUES (?, ?, ?)",
                (2, "YokeFunctionCalled", '{"context":'),
            )
        conn.commit()
        before = _snapshot(conn, table) if table else None
        _entry().apply(conn)
        _entry().invariants(conn)
        conn.rollback()
        if table:
            assert _snapshot(conn, table) == before
            with pytest.raises(AssertionError):
                _entry().invariants(conn)
        else:
            _entry().invariants(conn)
        assert SECRET not in capsys.readouterr().out
    finally:
        conn.close()
