"""One-time credentials never become replay results or debug captures."""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from pydantic import BaseModel
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.api.observability import service_name
from yoke_core.api.observability_debug import (
    DEBUG_MAX_RECORDS_ENV,
    DEBUG_SCOPE_ENV,
    DEBUG_UNTIL_ENV,
    reset_debug_state,
)
from yoke_core.domain import api_tokens, db_helpers
from yoke_core.domain import yoke_function_dispatch_events as events
from yoke_core.domain import yoke_function_registry as registry
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.admission_result_redaction import ONE_TIME_SECRET_GUARDRAIL
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.handlers import _register_profile, profile_tokens
from yoke_core.domain.yoke_function_dispatch import dispatch

from runtime.api.fixtures.dispatch_actor import authorize_every_dispatch

_SECRET = api_tokens.TOKEN_PREFIX + "testCredentialOnly" * 3
_FUNCTIONS = ("profile.token.create", "credential.synthetic.create")


class _CredentialResponse(BaseModel):
    credential: str


def _synthetic_create(request):
    outcome = profile_tokens.handle_profile_token_create(request)
    if outcome.primary_success:
        outcome.result_payload = {"credential": outcome.result_payload["raw_token"]}
    return outcome


def _request(function, actor, request_id="create-once", name="personal-key"):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=str(actor), session_id=""),
        target=TargetRef(kind="global"),
        request_id=request_id,
        payload={"name": name},
    )


@pytest.fixture
def secret_calls(test_db, monkeypatch, caplog):
    registry.reset_registry_for_tests()
    _register_profile.register(registry)
    registry.register(
        _FUNCTIONS[1],
        _synthetic_create,
        profile_tokens.ProfileTokenCreateRequest,
        _CredentialResponse,
        stability="internal",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=["api_tokens_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[ONE_TIME_SECRET_GUARDRAIL],
        adapter_status="internal",
        ambient_session_required=False,
    )
    actor = test_db.execute(
        "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    monkeypatch.setattr(api_tokens, "generate_token", lambda: _SECRET)
    emitted = Mock(wraps=events.emit_event)
    monkeypatch.setattr(events, "emit_event", emitted)
    monkeypatch.setenv(DEBUG_SCOPE_ENV, f"service:{service_name()}")
    monkeypatch.setenv(
        DEBUG_UNTIL_ENV,
        (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    monkeypatch.setenv(DEBUG_MAX_RECORDS_ENV, "100")
    caplog.set_level(logging.DEBUG, logger="yoke_core")
    reset_debug_state()
    try:
        with authorize_every_dispatch():
            yield actor, emitted
    finally:
        reset_debug_state()
        registry.reset_registry_for_tests()


def _assert_receipts_safe(conn, emitted, caplog, request_id, *, count):
    assert (
        conn.execute(
            "SELECT 1 FROM function_call_ledger WHERE request_id = %s",
            (request_id,),
        ).fetchone()
        is None
    )
    calls = [
        call for call in emitted.call_args_list if call.args[0] == "YokeFunctionCalled"
    ]
    assert len(calls) == count
    for call in calls:
        context = call.kwargs["context"]
        assert context["result_redacted"] == ONE_TIME_SECRET_GUARDRAIL
        assert "result" not in context
        assert _SECRET not in json.dumps(call.kwargs, default=str)
    assert _SECRET not in caplog.text
    return [call.kwargs["context"] for call in calls]


@pytest.mark.parametrize("function", _FUNCTIONS)
def test_secret_is_returned_once_without_a_ledger_or_debug_copy(
    test_db,
    secret_calls,
    caplog,
    function,
):
    actor, emitted = secret_calls
    request = _request(function, actor)
    response = dispatch(request, ambient_session_id="")
    assert response.success, response.error
    secret_key = "raw_token" if function == _FUNCTIONS[0] else "credential"
    assert response.result[secret_key] == _SECRET
    assert response.error is None
    row = test_db.execute(
        "SELECT actor_id, name, token_hash FROM api_tokens WHERE creation_request_id = %s",
        (request.request_id,),
    ).fetchone()
    assert tuple(row) == (actor, "personal-key", api_tokens.hash_token(_SECRET))
    contexts = _assert_receipts_safe(
        test_db, emitted, caplog, request.request_id, count=1
    )
    assert contexts[0]["result_keys"] == sorted(response.result)

    replay = dispatch(request, ambient_session_id="")
    assert not replay.success
    assert replay.result == {}
    assert replay.error.code == "result_unavailable"
    assert "yoke tokens list" in replay.error.message
    assert "yoke tokens revoke TOKEN-ID" in replay.error.message
    assert _SECRET not in replay.model_dump_json()
    assert (
        test_db.execute(
            "SELECT count(*) FROM api_tokens WHERE creation_request_id = %s",
            (request.request_id,),
        ).fetchone()[0]
        == 1
    )
    _assert_receipts_safe(test_db, emitted, caplog, request.request_id, count=2)


@pytest.mark.parametrize("function", _FUNCTIONS)
@pytest.mark.parametrize("name", ("", " " * 5, _SECRET * 3))
def test_invalid_names_do_not_echo_input_or_issue_credentials(
    test_db,
    secret_calls,
    caplog,
    function,
    name,
):
    actor, emitted = secret_calls
    request = _request(function, actor, name=name)
    response = dispatch(request, ambient_session_id="")
    assert not response.success
    assert response.error.code == "payload_invalid"
    assert _SECRET not in response.model_dump_json()
    assert (
        test_db.execute(
            "SELECT 1 FROM api_tokens WHERE creation_request_id = %s",
            (request.request_id,),
        ).fetchone()
        is None
    )
    _assert_receipts_safe(test_db, emitted, caplog, request.request_id, count=1)


def test_concurrent_profile_calls_issue_one_token(
    test_db, secret_calls, caplog, monkeypatch
):
    actor, emitted = secret_calls
    callers = threading.Barrier(2)

    def generate():
        callers.wait(timeout=10)
        return _SECRET

    monkeypatch.setattr(api_tokens, "generate_token", generate)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                dispatch,
                _request(_FUNCTIONS[0], actor),
                ambient_session_id="",
            )
            for _ in range(2)
        ]
        responses = [future.result(timeout=20) for future in futures]
    assert sum(response.success for response in responses) == 1
    refused = next(response for response in responses if not response.success)
    assert refused.error.code == "result_unavailable"
    assert _SECRET not in refused.model_dump_json()
    assert (
        test_db.execute(
            "SELECT count(*) FROM api_tokens WHERE creation_request_id = 'create-once'"
        ).fetchone()[0]
        == 1
    )
    _assert_receipts_safe(test_db, emitted, caplog, "create-once", count=2)


def test_unique_request_conflict_rolls_back_and_refuses(test_db):
    names = ("first-person", "second-person")
    actors = [seed_human_actor(test_db, name) for name in names]
    inserts = threading.Barrier(2)

    class ConcurrentConnection:
        def __init__(self, conn):
            self.conn = conn
            self.rolled_back = False

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def execute(self, sql, params=None):
            if sql.startswith("INSERT INTO api_tokens "):
                inserts.wait(timeout=10)
            return self.conn.execute(sql, params)

        def rollback(self):
            self.rolled_back = True
            self.conn.rollback()

    def create(actor):
        with db_helpers.connect() as raw:
            conn = ConcurrentConnection(raw)
            try:
                api_tokens.mint_token(
                    conn, actor_id=actor, name="key", creation_request_id="race"
                )
                return "created", conn.rolled_back
            except api_tokens.TokenCreationReplayed:
                assert conn.execute("SELECT 1").fetchone()[0] == 1
                return "replayed", conn.rolled_back

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, actors))
    assert sorted(results) == [("created", False), ("replayed", True)]
    assert (
        test_db.execute(
            "SELECT count(*) FROM api_tokens WHERE creation_request_id = 'race'"
        ).fetchone()[0]
        == 1
    )


def test_unrelated_integrity_error_is_not_a_replay(test_db):
    actor = test_db.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    api_tokens.mint_token(test_db, actor_id=actor, name="first", raw_token=_SECRET)
    with pytest.raises(api_tokens.db_backend.integrity_error_types(test_db)):
        api_tokens.mint_token(
            test_db,
            actor_id=actor,
            name="duplicate-hash",
            raw_token=_SECRET,
            creation_request_id="unrelated",
        )
    assert (
        test_db.execute(
            "SELECT 1 FROM api_tokens WHERE creation_request_id = 'unrelated'"
        ).fetchone()
        is None
    )


def test_auth_schema_converges_existing_tokens_without_rewriting_them(test_db):
    actor = test_db.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    created = api_tokens.mint_token(test_db, actor_id=actor, name="existing")
    test_db.execute("ALTER TABLE api_tokens DROP COLUMN creation_request_id")
    test_db.commit()
    create_auth_tables(test_db)
    create_auth_tables(test_db)
    row = test_db.execute(
        "SELECT token_hash, creation_request_id FROM api_tokens WHERE id = %s",
        (created.token_id,),
    ).fetchone()
    assert tuple(row) == (api_tokens.hash_token(created.raw_token), None)
    index = test_db.execute(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_api_tokens_creation_request'"
    ).fetchone()[0]
    assert "UNIQUE" in index and "creation_request_id IS NOT NULL" in index
