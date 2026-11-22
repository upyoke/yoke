"""A sign-in repairs same-server connections the server reports revoked."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from yoke_cli.commands import connect as commands
from yoke_cli.config import (
    hosted_machine_authorization,
    server_connect,
    writer,
    writer_credential_share,
)
from yoke_cli.transport import https
from yoke_contracts.api.function_call import FunctionCallResponse

_URL = "https://app.upyoke.com/api/orgs/acme"
_OLD = "yk-test-old-token-0123456789abcdefghijkl"
_NEW = "yk-test-new-token-0123456789abcdefghijkl"
_LIVE = "yk-test-live-token-0123456789abcdefghijk"
_PASTED = "yk-test-pasted-token-0123456789abcdefgh"


@pytest.fixture()
def home(monkeypatch, tmp_path) -> Path:
    path = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(path))
    from yoke_cli.config import onboard_session_relay as relay

    monkeypatch.setattr(
        relay, "install", lambda **_kw: relay.RelayInstallOutcome(True, False)
    )
    return path


def _server(monkeypatch, *, revoked=(_OLD,), unreachable=()) -> list[str]:
    probed: list[str] = []

    def fake_get(url, *, headers, timeout_s):
        if url.endswith("/v1/health"):
            return {"status": "ok", "build": "abc", "schema_ready": True}
        token = headers["Authorization"].removeprefix("Bearer ")
        probed.append(token)
        if token in revoked:
            raise server_connect._HttpFailure(
                "HTTP 401", code="authentication_revoked"
            )
        if token in unreachable:
            raise server_connect._HttpFailure("connection refused")
        return {"ok": True, "actor": {"id": 1, "label": "a"}, "token": {"id": 1}}

    monkeypatch.setattr(server_connect, "_http_get_json", fake_get)
    monkeypatch.setattr(
        hosted_machine_authorization,
        "authorize",
        lambda *_a, **_k: hosted_machine_authorization.HostedMachineCredential(
            api_url=_URL, org="acme", token=_NEW
        ),
    )
    monkeypatch.setattr(
        https,
        "relay_https",
        lambda request, *_a, **_k: FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            result={"credential": {"token": _NEW}},
        ),
    )
    return probed


def _save(name: str, token: str = _OLD, url: str = _URL) -> None:
    writer.set_connection(name, transport="https", api_url=url, token=token)


def _config(home: Path) -> dict:
    return json.loads((home / "config.json").read_text(encoding="utf-8"))


def _source(home: Path, name: str) -> dict:
    return _config(home)["connections"][name]["credential_source"]


def _token(home: Path, name: str) -> str:
    return Path(_source(home, name)["path"]).read_text(encoding="utf-8").strip()


def _sign_in(capsys, *extra: str) -> tuple[int, dict]:
    code = commands.connect(["--name", "second", "--json", *extra])
    return code, json.loads(capsys.readouterr().out)


def test_no_activate_repairs_revoked_active_connection(monkeypatch, home, capsys):
    _server(monkeypatch)
    _save("acme")
    old_file = Path(_source(home, "acme")["path"])

    code, report = _sign_in(capsys, "--no-activate")

    assert code == 0
    assert _config(home)["active_env"] == "acme"
    assert _source(home, "acme") == _source(home, "second")
    assert _token(home, "acme") == _NEW
    assert report["credential_shared_with"] == ["acme"]
    assert report["credential_unverified"] == []
    assert not old_file.exists()


def test_activating_sign_in_also_repairs_previous_connection(
    monkeypatch, home, capsys
):
    _server(monkeypatch)
    _save("acme")

    code, report = _sign_in(capsys)

    assert code == 0
    assert _config(home)["active_env"] == "second"
    assert _token(home, "acme") == _NEW
    assert report["credential_shared_with"] == ["acme"]


def test_working_token_on_same_server_is_left_alone(monkeypatch, home, capsys):
    _server(monkeypatch)
    _save("acme", token=_LIVE)
    before = _source(home, "acme")

    code, report = _sign_in(capsys, "--no-activate")

    assert code == 0
    assert _source(home, "acme") == before
    assert _token(home, "acme") == _LIVE
    assert report["credential_shared_with"] == []


def test_unverifiable_token_is_unchanged_and_reported(monkeypatch, home, capsys):
    _server(monkeypatch, revoked=(), unreachable=(_OLD,))
    _save("acme")
    before = _source(home, "acme")

    code, report = _sign_in(capsys, "--no-activate")

    assert code == 0
    assert _source(home, "acme") == before
    assert _token(home, "acme") == _OLD
    assert report["credential_shared_with"] == []
    assert report["credential_unverified"] == ["acme"]


def test_connections_sharing_a_revoked_file_move_together(monkeypatch, home, capsys):
    _server(monkeypatch)
    _save("acme")
    _save("third")
    payload = _config(home)
    payload["connections"]["third"]["credential_source"] = _source(home, "acme")
    (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    (home / "secrets" / "third.token").unlink()
    old_file = Path(_source(home, "acme")["path"])

    _code, report = _sign_in(capsys, "--no-activate")

    assert report["credential_shared_with"] == ["acme", "third"]
    assert _token(home, "third") == _NEW
    assert not old_file.exists()


def test_foreign_credential_file_is_kept(monkeypatch, home, tmp_path, capsys):
    _server(monkeypatch)
    _save("acme")
    foreign = tmp_path / "operator.token"
    foreign.write_text(_OLD + "\n", encoding="utf-8")
    foreign.chmod(0o600)
    payload = _config(home)
    payload["connections"]["acme"]["credential_source"]["path"] = str(foreign)
    (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")

    _code, report = _sign_in(capsys, "--no-activate")

    assert report["credential_shared_with"] == ["acme"]
    assert _token(home, "acme") == _NEW
    assert foreign.read_text(encoding="utf-8").strip() == _OLD


def test_failed_config_write_restores_old_file(monkeypatch, home, capsys):
    _server(monkeypatch)
    _save("acme")
    before = _source(home, "acme")
    old_file = Path(before["path"])

    def refuse(*_args, **_kwargs):
        raise writer.MachineConfigWriteError("disk full")

    monkeypatch.setattr(writer_credential_share, "write_payload", refuse)

    code, report = _sign_in(capsys, "--no-activate")

    assert code == 1
    assert "connection_credential_share_failed" in report["session_relay"]["error"]
    assert _source(home, "acme") == before
    assert old_file.read_text(encoding="utf-8").strip() == _OLD


def test_other_org_and_origin_are_never_checked(monkeypatch, home, capsys):
    probed = _server(monkeypatch, revoked=(_OLD, _LIVE))
    _save("other-org", token=_LIVE, url="https://app.upyoke.com/api/orgs/other")
    _save("other-origin", token=_LIVE, url="https://yoke.internal")

    _code, report = _sign_in(capsys, "--no-activate")

    assert report["credential_shared_with"] == []
    assert _token(home, "other-org") == _LIVE
    assert _token(home, "other-origin") == _LIVE
    assert _LIVE not in probed


def test_pasted_token_sign_in_also_repairs_revoked_connection(
    monkeypatch, home, capsys
):
    _server(monkeypatch)
    _save("acme")
    monkeypatch.setattr(sys, "stdin", io.StringIO(_PASTED))

    code = commands.connect(
        [_URL, "--name", "second", "--token-stdin", "--no-activate", "--json"]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert _config(home)["active_env"] == "acme"
    assert _token(home, "second") == _NEW
    assert _token(home, "acme") == _NEW
    assert report["credential_shared_with"] == ["acme"]


def test_removing_one_name_keeps_the_shared_file(monkeypatch, home, capsys):
    _server(monkeypatch)
    _save("acme")
    _sign_in(capsys, "--no-activate")

    result = writer.remove_connection("second")

    assert result["credential_retained_shared"] is True
    assert _token(home, "acme") == _NEW
