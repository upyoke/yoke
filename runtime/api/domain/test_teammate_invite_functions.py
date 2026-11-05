"""Invite form selection, org authority, one-time results and safe diagnostics."""

from runtime.api.domain.teammate_invite_codes_test_support import (_counts as _counts)
from runtime.api.domain.teammate_invite_functions_test_support import (_dispatch as _dispatch, _mode as _mode, _request as _request, calls as calls)


import json

import psycopg
import pytest
from yoke_contracts.timestamps import temporal_wire
from yoke_core.domain import teammate_invite_codes as invites
from yoke_core.domain.actors import seed_human_actor


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
        assert (
            not {"result", "result_redacted", "result_keys"}
            & call.kwargs["context"].keys()
        )
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


@pytest.mark.parametrize("name", ["  Avery  ", ""])
def test_create_reissue_and_list_publish_stored_time_and_inviter(test_db, calls, name):
    admin = calls[0]
    test_db.execute("UPDATE actors SET name=%s WHERE id=%s", (name, admin))
    test_db.commit()
    first = _dispatch(admin, "create", {"name": "Ana"}).result["invite"]
    second = _dispatch(admin, "reissue", {"invite_id": first["invite_id"]}).result[
        "invite"
    ]
    for row in (first, second):
        created_at, expires_at = test_db.execute(
            "SELECT created_at,expires_at FROM teammate_invite_codes WHERE id=%s",
            (row["invite_id"],),
        ).fetchone()
        assert row == {
            "invite_id": row["invite_id"],
            "ref": f"code-{row['invite_id']}",
            "kind": "code",
            "actor_id": first["actor_id"],
            "name": "Ana",
            "role": "operator",
            "state": "pending",
            "invited_by": name,
            "invited_by_name": name.strip() or None,
            "created_at": temporal_wire(created_at),
            "expires_at": temporal_wire(expires_at),
        }
    assert second["invite_id"] != first["invite_id"]
    assert second["created_at"] > first["created_at"]
    assert _dispatch(admin, "list", {"include_used": True}).result["invites"] == [
        second
    ]
