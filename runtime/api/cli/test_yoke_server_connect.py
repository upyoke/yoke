"""Tests for ``yoke connect URL`` — verify-then-persist server attach.

The HTTP layer is stubbed at the ``server_connect._http_get_json`` seam
(the same dynamic-seam style the local-universe CLI tests use). These
tests pin: verification-before-persistence (a failed health or identity
check writes NOTHING), the machine-config entry + token secret file
shape, activation semantics, the scheme policy, and tool-shaped command
resolution.
"""

from __future__ import annotations

import io
import json
import stat
import sys
from pathlib import Path

import pytest

from yoke_cli.commands import connect as commands
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.config import server_connect

_TOKEN = "yk-test-token-0123456789abcdefghijklmnop"


@pytest.fixture()
def machine_home(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


@pytest.fixture()
def token_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(_TOKEN))


def _stub_http(monkeypatch, *, healthy=True, authorized=True):
    calls = []

    def fake_get(url, *, headers, timeout_s):
        calls.append({"url": url, "headers": dict(headers)})
        if url.endswith("/v1/health"):
            if not healthy:
                raise server_connect._HttpFailure("connection refused")
            return {"status": "ok", "build": "abc123def456", "schema_ready": True}
        if url.endswith("/v1/auth/identity"):
            if not authorized:
                raise server_connect._HttpFailure("HTTP 401")
            return {
                "ok": True,
                "actor": {"id": 1, "label": "admin"},
                "token": {"id": 1, "name": "initial-admin"},
            }
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(server_connect, "_http_get_json", fake_get)
    return calls


def _config(home: Path) -> dict:
    return json.loads((home / "config.json").read_text(encoding="utf-8"))


def test_connect_verifies_then_writes_connection_and_token_file(
    monkeypatch,
    machine_home,
    token_stdin,
    capsys,
):
    calls = _stub_http(monkeypatch)
    assert commands.connect(["http://127.0.0.1:8765", "--token-stdin", "--json"]) == 0

    assert [c["url"] for c in calls] == [
        "http://127.0.0.1:8765/v1/health",
        "http://127.0.0.1:8765/v1/auth/identity",
    ]
    assert calls[1]["headers"]["Authorization"] == f"Bearer {_TOKEN}"

    config = _config(machine_home)
    entry = config["connections"]["self-host"]
    assert entry["transport"] == "https"
    assert entry["api_url"] == "http://127.0.0.1:8765"
    assert config["active_env"] == "self-host"
    source = entry["credential_source"]
    assert source["kind"] == "token_file"
    token_path = Path(source["path"])
    assert token_path == machine_home / "secrets" / "self-host.token"
    assert token_path.read_text(encoding="utf-8").strip() == _TOKEN
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600

    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["activated"] is True
    assert report["identity"]["actor"]["label"] == "admin"


def test_connect_custom_name_and_no_activate(
    monkeypatch,
    machine_home,
    token_stdin,
    capsys,
):
    _stub_http(monkeypatch)
    assert (
        commands.connect(
            [
                "https://yoke.internal",
                "--name",
                "team",
                "--token-stdin",
                "--no-activate",
                "--json",
            ]
        )
        == 0
    )
    config = _config(machine_home)
    assert config["connections"]["team"]["api_url"] == "https://yoke.internal"
    # No prior active_env: the connection writer still needs one to keep
    # the config valid, but --no-activate performed no activation step.
    report = json.loads(capsys.readouterr().out)
    assert report["activated"] is False


def test_connect_health_failure_persists_nothing(
    monkeypatch,
    machine_home,
    token_stdin,
    capsys,
):
    _stub_http(monkeypatch, healthy=False)
    assert commands.connect(["http://127.0.0.1:8765", "--token-stdin"]) == 1
    err = capsys.readouterr().err
    assert "nothing was persisted" in err
    assert not (machine_home / "config.json").exists()
    assert not (machine_home / "secrets").exists()


def test_connect_identity_failure_persists_nothing(
    monkeypatch,
    machine_home,
    token_stdin,
    capsys,
):
    _stub_http(monkeypatch, authorized=False)
    assert commands.connect(["http://127.0.0.1:8765", "--token-stdin"]) == 1
    err = capsys.readouterr().err
    assert "token verification failed" in err
    assert not (machine_home / "config.json").exists()
    assert not (machine_home / "secrets").exists()


def test_connect_rejects_non_http_scheme(
    monkeypatch,
    machine_home,
    token_stdin,
    capsys,
):
    calls = _stub_http(monkeypatch)
    assert commands.connect(["postgres://db.internal", "--token-stdin"]) == 1
    assert "unsupported URL scheme" in capsys.readouterr().err
    assert calls == []
    assert not (machine_home / "config.json").exists()


def test_connect_rejects_non_loopback_plain_http(
    monkeypatch,
    machine_home,
    token_stdin,
    capsys,
):
    calls = _stub_http(monkeypatch)

    assert commands.connect(["http://yoke.internal", "--token-stdin"]) == 1

    assert "numeric loopback" in capsys.readouterr().err
    assert calls == []
    assert not (machine_home / "config.json").exists()


def test_connect_help_requires_https_beyond_numeric_loopback(capsys):
    with pytest.raises(SystemExit) as raised:
        commands.connect(["--help"])

    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    assert "required for every network server" in help_text
    assert "accepted only for a numeric loopback endpoint" in help_text
    assert "plain http:// is accepted for self-host servers" not in help_text


def test_connect_token_file_source(monkeypatch, machine_home, tmp_path, capsys):
    _stub_http(monkeypatch)
    token_file = tmp_path / "pasted-token"
    token_file.write_text(_TOKEN + "\n", encoding="utf-8")
    assert (
        commands.connect(
            [
                "http://127.0.0.1:8765",
                "--token-file",
                str(token_file),
                "--json",
            ]
        )
        == 0
    )
    config = _config(machine_home)
    stored = Path(config["connections"]["self-host"]["credential_source"]["path"])
    assert stored.read_text(encoding="utf-8").strip() == _TOKEN


def test_connect_requires_exactly_one_token_source(machine_home, capsys):
    assert commands.connect(["http://127.0.0.1:8765"]) == 2
    err = capsys.readouterr().err
    assert "exactly one token source" in err
    assert not (machine_home / "config.json").exists()


def test_tool_shaped_resolution():
    resolved = resolve_tool_shaped(["connect", "http://x", "--token-stdin"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is commands.connect
    assert remaining == ["http://x", "--token-stdin"]
