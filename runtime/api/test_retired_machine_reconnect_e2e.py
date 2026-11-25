"""A retired computer reconnects without reinstalling, locally and to a server.

The server is the real Yoke app on a loopback port, the client is the real
connect code speaking HTTP, the machine config is a real file, and the local
universe is reached through the ordinary in-process dispatcher.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from runtime.api import web_sign_in_door_test_support as door
from runtime.api.fixtures.machine_config_test import select_machine_config_file
from runtime.api.fixtures.operating_actor import record_fixture_operating_actor
from yoke_cli.commands import connect
from yoke_cli.config import hosted_machine_authorization as auth
from yoke_cli.config import onboard_session_relay, writer
from yoke_cli.config.machine_registration import register_this_machine
from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_cli.transport.https import resolve_https_connection
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.machine_authorization import START_PATH
from yoke_contracts.machine_config import schema as contract
from yoke_core.api import app_factory
from yoke_core.domain import machine_registry
from yoke_core.domain.api_tokens import hash_token, mint_token
from yoke_core.domain.handlers.__init_register__ import register_all_handlers

_clean_oidc_env = door._clean_oidc_env
db_conn = door.db_conn

FIRST_ID = "3f0e8d52-7c1b-4b8e-9d6a-2a4c5e7f9b13"


@contextmanager
def _serve():
    server = uvicorn.Server(
        uvicorn.Config(
            app_factory.create_app(),
            host="127.0.0.1",
            port=0,
            log_level="error",
            ws="none",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline, "server_start_timeout"
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _call(function_id: str, payload: dict):
    response = call_dispatcher(
        function_id=function_id, target=TargetRef(kind="global"), payload=payload
    )
    assert response.success, response.error
    return response.result


def _configured_id(path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["machine_id"]


def _raw_start(origin: str, machine_id: str) -> tuple[int, dict]:
    body = {"machine_id": machine_id, "machine_name": "Build Host", "platform": "macOS"}
    request = urllib.request.Request(
        origin + START_PATH,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as reply:
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_retired_computer_reconnects_locally_then_to_a_self_hosted_server(
    db_conn, tmp_path, monkeypatch
):
    register_all_handlers()
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"schema_version": contract.SCHEMA_VERSION, "machine_id": FIRST_ID})
    )
    select_machine_config_file(monkeypatch, str(config))
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.setattr(auth, "machine_display_name", lambda: "Build Host")
    actor = int(
        db_conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    record_fixture_operating_actor(db_conn, actor)
    db_conn.commit()

    # Local universe: register, retire, then register again without reinstalling.
    assert register_this_machine()["registered"] is True
    _call("machine.retire", {"machine_id": FIRST_ID})
    again = register_this_machine()
    second_id = _configured_id(config)
    assert again["registered"] is True, again
    assert again["retired_machine_id"] == FIRST_ID
    assert again["machine_id"] == second_id != FIRST_ID
    assert machine_registry.get_machine(db_conn, FIRST_ID).retired_at is not None
    assert machine_registry.get_machine(db_conn, second_id).retired_at is None

    # Self-hosted server: retire this computer again and connect over HTTP.
    _call("machine.retire", {"machine_id": second_id})
    with _serve() as origin:
        status, refused = _raw_start(origin, second_id)
        assert (status, refused["error"]) == (409, "machine_retired")
        pending = auth.start(origin, self_host=True)
        assert pending.retired_machine_id == second_id == _configured_id(config)
        third_id = pending.draft_machine_id
        assert third_id and third_id != second_id
        _call(
            "machine_authorization.resolve",
            {"code": pending.user_code, "action": "approve"},
        )
        credential = auth.complete(pending)
    assert credential.token and _configured_id(config) == third_id
    reconnected = machine_registry.get_machine(db_conn, third_id)
    assert reconnected.retired_at is None and reconnected.owner_actor_id == actor
    for retired_id in (FIRST_ID, second_id):
        assert machine_registry.get_machine(db_conn, retired_id).retired_at is not None


def test_bootstrap_connect_binds_destination_without_activating_it(
    db_conn, tmp_path, monkeypatch
):
    register_all_handlers()
    actor = int(db_conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0])
    bootstrap = mint_token(db_conn, actor_id=actor, name="self-host-first-boot")
    db_conn.commit()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    config = tmp_path / "config.json"
    writer.set_connection(
        "local", transport="local-postgres", dsn="host=/sock dbname=yoke", path=config
    )
    path = tmp_path / "first-boot-token"
    path.write_text(bootstrap.raw_token)
    path.chmod(0o600)
    installs = []

    def install(*, environment, config_path, **_):
        https = resolve_https_connection(config_path, explicit_env=environment)
        installs.append((environment, hash_token(https.token)))
        return onboard_session_relay.RelayInstallOutcome(installed=True, reused=False)

    monkeypatch.setattr(onboard_session_relay, "install", install)
    with _serve() as origin:
        assert connect.connect([
            origin, "--token-file", str(path), "--name", "self-hosted",
            "--no-activate", "--config", str(config), "--json",
        ]) == 0
    payload = json.loads(config.read_text())
    assert payload["active_env"] == "local"
    [(environment, token_hash)] = installs
    assert environment == "self-hosted"
    row = db_conn.execute(
        "SELECT machine_id FROM api_tokens WHERE token_hash=%s", (token_hash,)
    ).fetchone()
    assert row[0] == payload["machine_id"]
    assert path.read_text() == bootstrap.raw_token
