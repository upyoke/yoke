"""Tests for the yoke CLI HTTPS transport routing."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from yoke_cli.transport import https as yoke_transport
from yoke_cli.transport.https import (
    HttpsConnection,
    TransportError,
    relay_https,
    resolve_https_connection,
)
from yoke_contracts.machine_config.schema import (
    MachineConfigContractError,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="events.query.run",
        actor=ActorContext(session_id="s1"),
        target=TargetRef(kind="global"),
        request_id="req-1",
        payload={"limit": 1},
    )


def _https_config(tmp_path, token="tok-123", api_url="https://api.example"):
    token_file = tmp_path / "token"
    token_file.write_text(token + "\n")
    return {
        "schema_version": 1,
        "active_env": "stage",
        "connections": {
            "stage": {
                "transport": "https",
                "api_url": api_url,
                "credential_source": {
                    "kind": "token_file",
                    "path": str(token_file),
                },
            },
        },
    }


def _stage_entry(config):
    return config["connections"]["stage"]


class TestResolveHttpsConnection:
    def test_https_connection_resolves_token(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            yoke_transport, "active_connection",
            lambda path=None, *, explicit_env=None: {
                **_stage_entry(_https_config(tmp_path)), "env": "stage"
            },
        )
        conn = resolve_https_connection()
        assert conn == HttpsConnection(
            api_url="https://api.example", token="tok-123", env="stage"
        )
        assert conn.functions_url == "https://api.example/v1/functions/call"

    def test_https_connection_accepts_versioned_api_base(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            yoke_transport, "active_connection",
            lambda path=None, *, explicit_env=None: {
                **_stage_entry(
                    _https_config(tmp_path, api_url="https://api.example/v1")
                ),
                "env": "stage",
            },
        )
        conn = resolve_https_connection()
        assert conn is not None
        assert conn.functions_url == "https://api.example/v1/functions/call"

    def test_local_transport_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            yoke_transport, "active_connection",
            lambda path=None, *, explicit_env=None: {"transport": "local-postgres"},
        )
        assert resolve_https_connection() is None

    def test_no_connection_returns_none(self, monkeypatch):
        def _raise(path=None, *, explicit_env=None):
            raise MachineConfigContractError("no connection")

        monkeypatch.setattr(yoke_transport, "active_connection", _raise)
        assert resolve_https_connection() is None

    def test_missing_api_url_fails_loudly(self, monkeypatch, tmp_path):
        config = _https_config(tmp_path, api_url="")
        monkeypatch.setattr(
            yoke_transport, "active_connection",
            lambda path=None, *, explicit_env=None: _stage_entry(config),
        )
        with pytest.raises(TransportError, match="api_url"):
            resolve_https_connection()

    def test_wrong_credential_kind_fails_loudly(self, monkeypatch, tmp_path):
        config = _https_config(tmp_path)
        _stage_entry(config)["credential_source"] = {
            "kind": "dsn_file", "path": "/x",
        }
        monkeypatch.setattr(
            yoke_transport, "active_connection",
            lambda path=None, *, explicit_env=None: _stage_entry(config),
        )
        with pytest.raises(TransportError, match="token_file"):
            resolve_https_connection()

    def test_unreadable_token_fails_loudly(self, monkeypatch, tmp_path):
        config = _https_config(tmp_path)
        _stage_entry(config)["credential_source"]["path"] = str(
            tmp_path / "absent"
        )
        monkeypatch.setattr(
            yoke_transport, "active_connection",
            lambda path=None, *, explicit_env=None: _stage_entry(config),
        )
        with pytest.raises(TransportError, match="unreadable"):
            resolve_https_connection()


def _ok_envelope() -> bytes:
    return json.dumps({
        "success": True,
        "function": "events.query.run",
        "version": "v1",
        "request_id": "req-1",
        "result": {"rows": []},
    }).encode()


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestRelayHttps:
    _CONN = HttpsConnection(api_url="https://api.example", token="tok-123")

    def test_success_envelope_round_trips(self, monkeypatch):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["auth"] = req.get_header("Authorization")
            captured["body"] = json.loads(req.data.decode())
            return _FakeResponse(_ok_envelope())

        monkeypatch.setattr(
            yoke_transport, "open_no_redirect", fake_urlopen
        )
        response = relay_https(_request(), self._CONN)
        assert response.success is True
        assert response.result == {"rows": []}
        assert captured["url"] == "https://api.example/v1/functions/call"
        assert captured["auth"] == "Bearer tok-123"
        assert captured["body"]["function"] == "events.query.run"
        assert captured["body"]["payload"] == {"limit": 1}

    def test_boundary_denial_envelope_passes_through(self, monkeypatch):
        denial = json.dumps({
            "success": False,
            "function": "events.query.run",
            "version": "v1",
            "error": {"code": "unauthorized", "message": "missing token"},
        }).encode()

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized", {}, io.BytesIO(denial)
            )

        monkeypatch.setattr(
            yoke_transport, "open_no_redirect", fake_urlopen
        )
        response = relay_https(_request(), self._CONN)
        assert response.success is False
        assert response.error.code == "unauthorized"

    def test_partial_boundary_denial_is_adopted(self, monkeypatch):
        """The auth boundary denies pre-dispatch, so its 401 body lacks
        function/version; the relay adopts the error into a full typed
        envelope (live shape observed on api.stage.upyoke.com)."""
        denial = json.dumps({
            "success": False,
            "error": {"code": "authentication_unknown",
                      "message": "API token is unknown"},
        }).encode()

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized", {}, io.BytesIO(denial)
            )

        monkeypatch.setattr(
            yoke_transport, "open_no_redirect", fake_urlopen
        )
        response = relay_https(_request(), self._CONN)
        assert response.success is False
        assert response.error.code == "authentication_unknown"
        assert response.function == "events.query.run"

    def test_non_envelope_http_error_synthesizes_transport_error(
        self, monkeypatch
    ):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 502, "Bad Gateway", {},
                io.BytesIO(b"<html>bad gateway</html>"),
            )

        monkeypatch.setattr(
            yoke_transport, "open_no_redirect", fake_urlopen
        )
        response = relay_https(_request(), self._CONN)
        assert response.success is False
        assert response.error.code == "https_transport_failed"
        assert "502" in response.error.message
        assert "yoke status" in response.error.recovery_hint

    def test_unreachable_host_synthesizes_transport_error(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(
            yoke_transport, "open_no_redirect", fake_urlopen
        )
        response = relay_https(_request(), self._CONN)
        assert response.success is False
        assert response.error.code == "https_transport_failed"
        assert "could not reach" in response.error.message
