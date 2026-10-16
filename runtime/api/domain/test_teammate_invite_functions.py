"""Invite form selection, org authority, one-time results and safe diagnostics."""

import json
import logging
from datetime import timedelta
from unittest.mock import Mock

import psycopg
import pytest
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.server_mode import SERVER_MODE_ENV
from yoke_contracts.timestamps import utc_now
from yoke_core.api import oidc_config
from yoke_core.api.observability import service_name
from yoke_core.api.observability_debug import (
    DEBUG_MAX_RECORDS_ENV,
    DEBUG_SCOPE_ENV,
    DEBUG_UNTIL_ENV,
    reset_debug_state,
)
from yoke_core.domain import teammate_invite_codes as invites
from yoke_core.domain import universe_startup_lock
from yoke_core.domain import yoke_function_dispatch_events as events
from yoke_core.domain import yoke_function_registry as registry
from yoke_core.domain.actor_permissions import (
    grant_actor_org_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.handlers import _register_teammate_invites, identity_invites
from yoke_core.domain.yoke_function_dispatch import dispatch


def _mode(monkeypatch, mode="self-host", oidc="none"):
    monkeypatch.setattr(
        universe_startup_lock,
        "hosted_tenant_container_process",
        lambda: mode == "hosted",
    )
    monkeypatch.setattr(
        identity_invites, "hosted_tenant_container_process", lambda: mode == "hosted"
    )
    monkeypatch.delenv(SERVER_MODE_ENV, raising=False)
    if mode != "local":
        monkeypatch.setenv(SERVER_MODE_ENV, "self-host")
    for key in vars(oidc_config):
        if key.endswith("_ENV"):
            monkeypatch.delenv(getattr(oidc_config, key), raising=False)
    if oidc != "none":
        monkeypatch.setenv(oidc_config.OIDC_ISSUER_ENV, "https://identity.example")
    if oidc == "complete":
        monkeypatch.setenv(oidc_config.OIDC_CLIENT_ID_ENV, "client")
        monkeypatch.setenv(oidc_config.OIDC_CLIENT_SECRET_ENV, "test-secret")
        monkeypatch.setenv(oidc_config.OIDC_REDIRECT_URL_ENV, "https://team.example")


@pytest.fixture
def calls(test_db, monkeypatch, caplog):
    _mode(monkeypatch)
    seed_roles_and_permissions(test_db)
    admin = seed_human_actor(test_db, "Admin")
    grant_actor_org_role(
        test_db, actor_id=admin, org_id=default_org_id(test_db), role_name="admin"
    )
    registry.reset_registry_for_tests()
    _register_teammate_invites.register(registry)
    emitted = Mock(wraps=events.emit_event)
    monkeypatch.setattr(events, "emit_event", emitted)
    monkeypatch.setenv(DEBUG_SCOPE_ENV, f"service:{service_name()}")
    monkeypatch.setenv(DEBUG_UNTIL_ENV, (utc_now() + timedelta(hours=1)).isoformat())
    monkeypatch.setenv(DEBUG_MAX_RECORDS_ENV, "100")
    caplog.set_level(logging.DEBUG, logger="yoke_core")
    reset_debug_state()
    try:
        yield admin, emitted
    finally:
        reset_debug_state()
        registry.reset_registry_for_tests()


def _request(actor, operation, payload=None, request_id=None):
    return FunctionCallRequest(
        function=f"teammate_invites.{operation}",
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id=str(actor), session_id=""),
        payload=payload or {},
        request_id=request_id,
    )


def _dispatch(actor, operation, payload=None, request_id=None):
    return dispatch(
        _request(actor, operation, payload, request_id), ambient_session_id=""
    )


def _counts(conn):
    return tuple(
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("actors", "actor_org_roles", "teammate_invite_codes")
    )


def _secret_request(conn, actor, operation):
    if operation == "create":
        return {"name": "Ana"}
    initial = invites.create_invite(conn, name="Ana", inviter_actor_id=actor)
    return {"invite_id": initial.invite["invite_id"]}


def _safe(conn, emitted, caplog, request_id, count):
    assert (
        conn.execute(
            "SELECT 1 FROM function_call_ledger WHERE request_id=%s", (request_id,)
        ).fetchone()
        is None
    )
    called = [c for c in emitted.call_args_list if c.args[0] == "YokeFunctionCalled"]
    assert len(called) == count
    for call in called:
        assert call.kwargs["context"]["result_redacted"] == "one_time_secret_result"
        assert "result" not in call.kwargs["context"]
        assert "yinv_" not in json.dumps(call.kwargs, default=str)
    assert "yinv_" not in caplog.text


@pytest.mark.parametrize("operation", ["create", "reissue"])
def test_admin_receives_code_once_and_replay_creates_nothing(
    test_db, calls, caplog, operation
):
    admin, emitted = calls
    payload = _secret_request(test_db, admin, operation)
    response = _dispatch(admin, operation, payload, "issue-once")
    assert response.success, response.error
    result = response.result
    assert invites.parse_invite_code(result["code"]) == result["code"]
    assert result["invite"]["role"] == "operator"
    assert result["expires_at"] == result["invite"]["expires_at"]
    assert (
        result["guidance"]["send_to"]
        == "send it to Ana only, through a private channel"
    )
    assert result["guidance"]["redeem_command"] == "yoke connect <origin>"
    assert "Enter invite code" in result["guidance"]["redeem_instruction"]
    before = _counts(test_db)
    replay = _dispatch(admin, operation, payload, "issue-once")
    assert not replay.success and replay.error.code == "result_unavailable"
    assert "yinv_" not in replay.model_dump_json()
    assert _counts(test_db) == before
    _safe(test_db, emitted, caplog, "issue-once", 2)


@pytest.mark.parametrize("operation", ["create", "reissue"])
@pytest.mark.parametrize(
    "refusal", ["invite_store_unavailable", "invite_email_required"]
)
def test_secret_refusals_do_not_log_or_echo_codes(
    test_db, calls, monkeypatch, caplog, operation, refusal
):
    admin, emitted = calls
    payload = _secret_request(test_db, admin, operation)
    before = _counts(test_db)
    if refusal == "invite_email_required":
        _mode(monkeypatch, oidc="complete")
    else:

        def fail(*args, **kwargs):
            raise psycopg.OperationalError("database error carrying yinv_" + "a" * 32)

        monkeypatch.setattr(invites, f"{operation}_invite", fail)
    response = _dispatch(admin, operation, payload, "refused")
    assert not response.success and response.error.code == refusal
    assert "yinv_" not in response.model_dump_json()
    assert _counts(test_db) == before
    _safe(test_db, emitted, caplog, "refused", 1)


@pytest.mark.parametrize("operation", ["create", "list", "revoke", "reissue"])
def test_non_admin_is_refused_before_invite_work(test_db, calls, operation):
    outsider = seed_human_actor(test_db, "Outsider")
    payload = (
        {"name": "Ana"}
        if operation == "create"
        else {}
        if operation == "list"
        else {"invite_id": 1}
    )
    before = _counts(test_db)
    response = _dispatch(outsider, operation, payload)
    assert not response.success and response.error.code == "permission_denied"
    assert _counts(test_db) == before


def test_list_revoke_and_reissue_keep_the_invited_actor(test_db, calls):
    admin = calls[0]
    created = _dispatch(admin, "create", {"name": "Ana", "role": "viewer"}).result
    invite = created["invite"]
    payload = {"invite_id": invite["invite_id"]}
    assert _dispatch(admin, "list").result["invites"] == [invite]
    assert _dispatch(admin, "revoke", payload).result["invite"]["state"] == "revoked"
    assert _dispatch(admin, "list").result["invites"] == []
    assert (
        _dispatch(admin, "list", {"include_used": True}).result["invites"][0]["state"]
        == "revoked"
    )
    before = _counts(test_db)
    issued = _dispatch(admin, "reissue", payload).result
    assert issued["invite"]["actor_id"] == invite["actor_id"]
    assert issued["code"] != created["code"] and issued["invite"]["role"] == "viewer"
    assert _counts(test_db) == (before[0], before[1], before[2] + 1)
