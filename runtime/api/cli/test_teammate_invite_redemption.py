"""Real unauthenticated invite delivery and private terminal connection flows."""

import io
import json
import logging
import stat
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from runtime.api.domain.test_teammate_invite_codes import _create, store as store
from runtime.api.test_web_sign_in_door import _clean_oidc_env as _clean_oidc_env
from yoke_cli.commands import connect
from yoke_cli.config import hosted_machine_authorization as auth, server_connect
from yoke_cli.config import teammate_invite_redemption as redemption
from yoke_cli.config import team_server_authorization as team
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpResponse,
    BoundedJsonHttpStatusError,
)
from yoke_contracts.teammate_invite_wire import INVITE_REDEEM_PATH
from yoke_contracts.timestamps import utc_now
from yoke_core.api import app_factory
from yoke_core.domain import events, machine_credentials
from yoke_core.domain.api_tokens import verify_token

ORIGIN = "https://team.example"
FLAG = "--invite-code-stdin"


@pytest.fixture
def endpoint(store, monkeypatch, caplog, tmp_path):
    caplog.set_level(logging.DEBUG, logger="yoke_core")
    caplog.set_level(logging.DEBUG, logger="yoke.api")
    monkeypatch.setattr(events, "emit_event", lambda *a, **k: None)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    identity = {"machine_id": str(uuid4()), "machine_name": "Teammate laptop"}
    monkeypatch.setattr(auth, "_machine_identity", lambda: identity)
    created = _create(store)
    with TestClient(app_factory.create_app(), base_url=ORIGIN) as client:
        yield client, created, {**identity, "platform": "Linux"}


def _send(client, invite, machine):
    return client.post(INVITE_REDEEM_PATH, json={**machine, "invite_code": invite.code})


def _row(conn, sql):
    return conn.execute(sql).fetchone()


def _bridge(monkeypatch, client):
    def send(request, **kwargs):
        assert request.full_url == ORIGIN + INVITE_REDEEM_PATH
        assert request.get_method() == "POST" and kwargs["replay_safe"] is False
        payload = json.loads(request.data)
        assert kwargs["sensitive_values"] == (payload["invite_code"],)
        response = client.post(INVITE_REDEEM_PATH, json=payload)
        if response.status_code != 200:
            raise BoundedJsonHttpStatusError(response.status_code, response.json())
        return BoundedJsonHttpResponse(response.json(), 200, response.headers)

    monkeypatch.setattr(redemption, "request_json", send)
    monkeypatch.setattr(
        team, "sign_in_methods", lambda _: team.SignInMethods(True, False)
    )

    def get(url, *, headers, timeout_s):
        if url.endswith("/health"):
            return {"status": "ok", "schema_ready": True}
        response = client.get("/v1/auth/identity", headers=headers)
        assert response.status_code == 200
        return response.json()

    monkeypatch.setattr(server_connect, "_http_get_json", get)
    return send


@pytest.mark.parametrize("json_mode", [False, True])
def test_connected_actor_and_secret_free_facts(
    endpoint, store, monkeypatch, tmp_path, capsys, caplog, json_mode
):
    client, created, machine = endpoint
    _bridge(monkeypatch, client)
    monkeypatch.setattr(sys, "stdin", io.StringIO(created.code))
    assert connect.connect([ORIGIN, FLAG, *(["--json"] if json_mode else [])]) == 0
    config = json.loads((tmp_path / "machine/config.json").read_text())
    credential_path = Path(
        config["connections"][config["active_env"]]["credential_source"]["path"]
    )
    token = credential_path.read_text().strip()
    conn, observer, inviter, _ = store
    verified = verify_token(conn, token)
    assert verified.actor_id == created.invite["actor_id"] != inviter
    assert stat.S_IMODE(credential_path.stat().st_mode) == 0o600
    row = _row(
        observer, "SELECT consumed_at,consumed_machine_id FROM teammate_invite_codes"
    )
    assert row[0] is not None and row[1] == machine["machine_id"]
    assert _row(observer, "SELECT owner_actor_id FROM machines") == (verified.actor_id,)
    audit = _row(
        observer,
        "SELECT actor_id,event_type,outcome FROM api_token_audit WHERE event_type='issued'",
    )
    assert audit == (verified.actor_id, "issued", "success")
    facts = repr(
        [
            observer.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("teammate_invite_codes", "machines", "api_token_audit")
        ]
    )
    output = capsys.readouterr()
    visible = output.out + output.err + caplog.text + facts + json.dumps(config)
    for secret in (created.code, token):
        assert secret not in visible
    if json_mode:
        assert json.loads(output.out)["identity"]["actor"]["id"] == verified.actor_id
    assert client.post(INVITE_REDEEM_PATH + "/extra", json={}).status_code == 401


@pytest.mark.parametrize(
    "reason,status",
    zip(
        "invalid expired revoked consumed machine_owned actor_disabled rate".split(),
        [404, 410, 410, 410, 409, 403, 429],
    ),
)
def test_route_refusal_privacy(endpoint, store, caplog, reason, status):
    client, created, machine = endpoint
    conn, _, inviter, _ = store
    tokens = []
    if reason in {"expired", "revoked"}:
        column = "expires_at" if reason == "expired" else "revoked_at"
        conn.execute(
            f"UPDATE teammate_invite_codes SET {column}=%s",
            (utc_now() - timedelta(seconds=1),),
        )
    elif reason == "actor_disabled":
        conn.execute(
            "UPDATE actors SET status='disabled' WHERE id=%s",
            (created.invite["actor_id"],),
        )
    elif reason == "consumed":
        tokens.append(_send(client, created, machine).json()["token"])
    elif reason == "machine_owned":
        identity = {
            "machine_id": machine["machine_id"],
            "name": machine["machine_name"],
        }
        _, _, credential = machine_credentials.register_with_credential(
            conn, **identity, actor_id=inviter, now=utc_now()
        )
        tokens.append(credential.token)
    conn.commit()
    code = "yinv_" + "a" * 32 if reason in {"invalid", "rate"} else created.code
    payload = {**machine, "invite_code": code}
    for _ in range(7 if reason == "rate" else 1):
        response = client.post(INVITE_REDEEM_PATH, json=payload)
    assert response.status_code == status
    expected = (
        "authorization_invite_redeem_rate_limited"
        if reason == "rate"
        else "invite_" + ("code_invalid" if reason == "invalid" else reason)
    )
    assert response.json()["error"] == expected
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["message"]
    if reason == "rate":
        assert int(response.headers["retry-after"]) > 0
    for secret in (created.code, payload["invite_code"], *tokens):
        assert secret not in caplog.text + response.text


def test_concurrent_route_redemption_issues_one_credential(endpoint, store):
    client, created, machine = endpoint
    barrier = Barrier(2)

    def send(_):
        barrier.wait(timeout=10)
        return _send(client, created, {**machine, "machine_id": str(uuid4())})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 410]
    refusal = next(r for r in responses if r.status_code == 410).json()
    assert refusal["error"] == "invite_consumed"
    assert _row(store[1], "SELECT count(*) FROM api_tokens") == (1,)


@pytest.mark.parametrize(
    "reason",
    (
        "invite_code_invalid invite_expired invite_revoked invite_consumed "
        "invite_actor_disabled invite_machine_owned machine_identity_required "
        "result_unavailable invite_email_required invite_local_universe "
        "invite_reissue_disabled_actor oidc_misconfigured "
        "authorization_invite_redeem_rate_limited"
    ).split(),
)
def test_cli_refusal_recovery(endpoint, monkeypatch, capsys, reason):
    client, created, _ = endpoint
    _bridge(monkeypatch, client)

    def refuse(*args, **kwargs):
        raise BoundedJsonHttpStatusError(
            429 if "rate_limited" in reason else 409,
            {"error": reason, "message": created.code + " raw-credential"},
        )

    monkeypatch.setattr(redemption, "request_json", refuse)
    monkeypatch.setattr(sys, "stdin", io.StringIO(created.code))
    assert connect.connect([ORIGIN, FLAG, "--json"]) == 1
    output = capsys.readouterr()
    assert reason + ":" in output.err and redemption._RECOVERY[reason] in output.err
    assert created.code not in output.out + output.err
    assert "raw-credential" not in output.err


@pytest.mark.parametrize("fault", ["lost", "origin", "schema"])
def test_failed_delivery_privacy(endpoint, store, monkeypatch, tmp_path, capsys, fault):
    client, created, _ = endpoint
    send = _bridge(monkeypatch, client)
    issued = []

    def fail(request, **kwargs):
        result = send(request, **kwargs)
        issued.append(result.payload["token"])
        if fault == "lost":
            raise BoundedJsonHttpError(created.code + issued[0])
        result.payload["api_url"] = "https://elsewhere.example"
        if fault == "schema":
            result.payload["secret"] = created.code
        return result

    monkeypatch.setattr(redemption, "request_json", fail)
    monkeypatch.setattr(sys, "stdin", io.StringIO(created.code))
    assert connect.connect([ORIGIN, FLAG, "--json"]) == 1
    output = capsys.readouterr()
    assert "reissue" in output.err and "retire" in output.err
    if fault == "origin":
        assert "invite_origin_mismatch" in output.err
    assert not (tmp_path / "machine/config.json").exists()
    assert _row(store[1], "SELECT consumed_at FROM teammate_invite_codes")[0]
    assert all(s not in output.out + output.err for s in [created.code, *issued])


@pytest.mark.parametrize("choice", ["3", "2", "cancel"])
def test_cancel_preserves_config(endpoint, monkeypatch, tmp_path, capsys, choice):
    client, _, _ = endpoint
    _bridge(monkeypatch, client)
    path = tmp_path / "existing.json"
    original = b'{"active_env":"existing","connections":{"existing":{"transport":"https","api_url":"https://existing.example"}}}\n'
    path.write_bytes(original)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def answer():
        if choice == "cancel":
            raise KeyboardInterrupt
        return choice

    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(redemption.getpass, "getpass", lambda _: "")
    assert connect.connect([ORIGIN, "--config", str(path)]) == 0
    assert path.read_bytes() == original
    assert "This is my own machine" in capsys.readouterr().err


@pytest.mark.parametrize(
    "company,tty,choice", [(False, True, "1"), (False, False, None), (True, True, None)]
)
def test_choices_and_notice(monkeypatch, capsys, company, tty, choice):
    monkeypatch.setattr(connect, "active_connection_is_local", lambda _: True)

    def methods(_):
        assert "Reachable here only" in capsys.readouterr().err
        return team.SignInMethods(True, company)

    monkeypatch.setattr(team, "sign_in_methods", methods)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty)
    monkeypatch.setattr("builtins.input", lambda: choice)
    monkeypatch.setattr(
        connect, "_connect_hosted", lambda p: 0 if p.invite_code is None else 99
    )
    assert connect.connect([ORIGIN]) == 0
    assert ("Enter invite code" in capsys.readouterr().err) == bool(choice)


@pytest.mark.parametrize(
    "args",
    [[FLAG], [ORIGIN, FLAG, "--token-stdin"], [ORIGIN, FLAG, "--token-file", "secret"]],
)
def test_invite_flag_usage_errors(args):
    assert connect.connect(args) == 2
