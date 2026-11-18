"""Connecting converges the saved destination's relay without changing selection."""

import io
import json
import subprocess
import sys

import pytest

from yoke_cli.commands import connect
from yoke_cli.config import hosted_machine_authorization as auth
from yoke_cli.config import onboard_session_relay as relay
from yoke_cli.config import server_connect, writer
from yoke_cli.transport import https
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError

BOOTSTRAP = "private-credential"
BOUND = "yk-destination-machine-test-credential"


@pytest.fixture
def machine(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO(BOOTSTRAP))
    monkeypatch.setattr(
        server_connect,
        "_http_get_json",
        lambda *a, **kw: {"ok": True, "actor": {"id": 1}},
    )
    monkeypatch.setattr(relay.sys, "platform", "linux")
    monkeypatch.setattr(https, "relay_https", register_reply)

    def ambient_wait(_timeout):
        pytest.fail("another active connection must not provide readiness")

    monkeypatch.setattr(relay, "_wait_for_connection", ambient_wait)
    return tmp_path


def register_reply(request, connection, **_):
    assert request.function == "machine.register"
    assert connection.token == BOOTSTRAP
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        result={
            "machine": {"machine_id": request.payload["machine_id"]},
            "credential": {"token": BOUND},
        },
    )


def installer(monkeypatch, *, failure=False):
    calls = []

    def run(action, **kwargs):
        calls.append((action, kwargs["environment"], kwargs["config_path"]))
        code = 1 if action == "status" or failure else 0
        return subprocess.CompletedProcess(
            [], code, "", "token=private-credential" if failure else ""
        )

    monkeypatch.setattr(relay, "_run", run)
    return calls


@pytest.mark.parametrize("browser", [False, True])
def test_connect_installs_saved_destination_relay(
    monkeypatch, machine, capsys, browser
):
    calls = installer(monkeypatch)
    if browser:
        monkeypatch.setattr(
            auth,
            "authorize",
            lambda *a, **kw: auth.HostedMachineCredential(
                "https://team.example", "selected", "private-credential"
            ),
        )
        args = []
    else:
        args = ["http://127.0.0.1:8765", "--token-stdin"]
    assert connect.connect([*args, "--name", "selected", "--json"]) == 0
    assert calls == [
        ("status", "selected", str(machine / "config.json")),
        ("install", "selected", str(machine / "config.json")),
    ]
    report = json.loads(capsys.readouterr().out)
    assert report["session_relay"] == {"installed": True, "reused": False}
    assert "ready" not in report["session_relay"]


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("json_mode", [False, True])
def test_custom_config_no_activate_scopes_install_and_partial_failure(
    monkeypatch, machine, capsys, failure, json_mode
):
    path = machine / "other config.json"
    writer.set_connection(
        "local",
        transport="local-postgres",
        dsn="host=/sock dbname=yoke",
        path=str(path),
    )
    writer.set_active_env("local", path=str(path))
    token_file = machine / "bootstrap"
    token_file.write_text(BOOTSTRAP)
    token_file.chmod(0o600)
    registrations = []

    def register(request, connection, **kwargs):
        registrations.append((connection.env, request.payload["machine_id"]))
        return register_reply(request, connection, **kwargs)

    monkeypatch.setattr(https, "relay_https", register)
    calls = installer(monkeypatch, failure=failure)
    code = connect.connect(
        [
            "http://127.0.0.1:8765",
            "--token-file",
            str(token_file),
            "--name",
            "second",
            "--config",
            str(path),
            "--no-activate",
            *(["--json"] if json_mode else []),
        ]
    )
    assert code == int(failure)
    config = json.loads(path.read_text())
    assert config["active_env"] == "local"
    assert {"local", "second"} <= set(config["connections"])
    assert registrations == [("second", config["machine_id"])]
    assert https.resolve_https_connection(path, explicit_env="second").token == BOUND
    assert token_file.read_text() == BOOTSTRAP
    assert calls == [("status", "second", str(path)), ("install", "second", str(path))]
    output = capsys.readouterr()
    assert BOOTSTRAP not in output.out + output.err
    assert BOUND not in output.out + output.err
    if json_mode:
        report = json.loads(output.out)
        assert report["session_relay"]["installed"] is not failure
    if failure:
        if json_mode:
            assert report["ok"] is False and report["connection_saved"] is True
        error = report["session_relay"]["error"] if json_mode else output.err
        assert "connection saved; relay setup failed" in error
        assert "--environment second" in error
        assert str(path) in error
        assert "<redacted>" in error


def test_registration_refusal_keeps_saved_connection_without_installing(
    monkeypatch, machine, capsys
):
    calls = installer(monkeypatch)
    monkeypatch.setattr(
        https, "relay_https",
        lambda request, *_args, **_kwargs: FunctionCallResponse(
            success=False,
            function=request.function,
            version=request.version,
            error=FunctionError(code="machine_owner_mismatch", message="owner rejected"),
        ),
    )
    assert connect.connect(["http://127.0.0.1:8765", "--token-stdin", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["connection_saved"] and not report["ok"]
    assert "machine_owner_mismatch" in report["session_relay"]["error"]
    assert "rerun the same `yoke connect`" in report["session_relay"]["error"]
    assert https.resolve_https_connection(machine / "config.json").token == BOOTSTRAP
    assert not calls


def test_failed_server_verification_never_installs_relay(monkeypatch, machine, capsys):
    calls = installer(monkeypatch)

    def unavailable(*a, **kw):
        raise server_connect._HttpFailure("server unavailable")

    monkeypatch.setattr(server_connect, "_http_get_json", unavailable)
    assert connect.connect(["http://127.0.0.1:8765", "--token-stdin"]) == 1
    assert calls == []
    assert not (machine / "config.json").exists()
    assert "nothing was persisted" in capsys.readouterr().err


def test_reconnect_reuses_current_destination_relay(monkeypatch, machine, capsys):
    calls = []

    def current(action, **kwargs):
        calls.append((action, kwargs["environment"]))
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(relay, "_run", current)
    assert connect.connect(["http://127.0.0.1:8765", "--token-stdin", "--json"]) == 0
    assert calls == [("status", "self-host")]
    assert json.loads(capsys.readouterr().out)["session_relay"] == {
        "installed": True,
        "reused": True,
    }
