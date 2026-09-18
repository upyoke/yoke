"""Engine-version handshake carried on HTTPS relay responses."""

from __future__ import annotations

import io
import json
import urllib.error

from yoke_cli.transport import control_plane_payload
from yoke_cli.transport import https as yoke_transport
from yoke_cli.transport import https_engine_handshake as yoke_handshake
from yoke_cli.transport.dispatcher import emit_response
from yoke_cli.transport.https import HttpsConnection, relay_https
from yoke_cli.transport.https_engine_handshake import ServerHandshake
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
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


def _ok_envelope() -> bytes:
    return json.dumps({
        "success": True,
        "function": "events.query.run",
        "version": "v1",
        "request_id": "req-1",
        "result": {"events": []},
    }).encode()


class _FakeResponse:
    def __init__(self, body: bytes, headers: dict | None = None):
        self._body = body
        self.headers = dict(headers or {})

    def read(self, *_args, **_kwargs) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class TestEngineVersionHandshakeStaysQuiet:
    """The handshake records skew and prints nothing.

    An advisory on every relay response repeated itself hundreds of times a
    session. Skew is now named only where it changes a decision: a payload
    or relay-build refusal, doctor, and the fleet report.
    """

    _CONN = HttpsConnection(api_url="https://api.example", token="tok-123")

    def _relay_with_header(
        self, monkeypatch, headers: dict
    ) -> FunctionCallResponse:
        def fake_urlopen(req, timeout=None):
            resp = _FakeResponse(_ok_envelope())
            resp.headers = dict(headers)
            return resp

        monkeypatch.setattr(
            yoke_transport, "open_no_redirect", fake_urlopen
        )
        response = relay_https(_request(), self._CONN)
        assert response.success is True
        return response

    def test_version_mismatch_prints_nothing(self, monkeypatch, capsys):
        monkeypatch.setattr(
            yoke_handshake, "local_handshake_version", lambda: "1.0.0"
        )
        header = {yoke_handshake.ENGINE_VERSION_HEADER: "2.0.0"}

        self._relay_with_header(monkeypatch, header)
        self._relay_with_header(monkeypatch, header)

        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""

    def test_mismatch_is_still_recorded_for_refusal_readers(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            yoke_handshake, "local_handshake_version", lambda: "1.0.0"
        )
        self._relay_with_header(
            monkeypatch, {yoke_handshake.ENGINE_VERSION_HEADER: "2.0.0"}
        )
        assert control_plane_payload.current_server_build().name == "v2.0.0"

    def test_json_emission_carries_no_advisory_on_either_stream(
        self, monkeypatch, capsys,
    ):
        monkeypatch.setattr(
            yoke_handshake, "local_handshake_version", lambda: "1.0.0"
        )

        response = self._relay_with_header(
            monkeypatch,
            {yoke_handshake.ENGINE_VERSION_HEADER: "2.0.0"},
        )
        assert emit_response(response, json_mode=True) == 0

        captured = capsys.readouterr()
        assert json.loads(captured.out)["success"] is True
        assert captured.out.count("\n") == 1
        assert captured.err == ""

    def test_matching_versions_stay_silent(self, monkeypatch, capsys):
        monkeypatch.setattr(
            yoke_handshake, "local_handshake_version", lambda: "2.0.0"
        )
        self._relay_with_header(
            monkeypatch, {yoke_handshake.ENGINE_VERSION_HEADER: "2.0.0"}
        )
        assert capsys.readouterr().err == ""

    def test_absent_header_stays_silent(self, monkeypatch, capsys):
        monkeypatch.setattr(
            yoke_handshake, "local_handshake_version", lambda: "1.0.0"
        )
        self._relay_with_header(monkeypatch, {})
        assert capsys.readouterr().err == ""

    def test_source_checkout_ahead_records_without_printing(
        self, monkeypatch, capsys,
    ):
        from yoke_cli.transport import source_build_skew as skew

        monkeypatch.setattr(yoke_handshake, "local_handshake_version", lambda: "")
        ahead = skew.BuildComparison(skew.AHEAD, ahead_by=2, server_build="v2.0.0")
        monkeypatch.setattr(skew, "compare_to_server_build", lambda *_a: ahead)

        self._relay_with_header(
            monkeypatch, {yoke_handshake.ENGINE_VERSION_HEADER: "2.0.0"}
        )

        assert capsys.readouterr().err == ""
        observed = control_plane_payload.current_server_build()
        assert observed.comparison is not None
        assert observed.comparison.relationship == skew.AHEAD

    def test_error_response_headers_also_feed_the_handshake(
        self, monkeypatch, capsys,
    ):
        """A 401 denial still advertises the server version; still no banner."""
        monkeypatch.setattr(
            yoke_handshake, "local_handshake_version", lambda: "1.0.0"
        )
        denial = json.dumps({
            "success": False,
            "error": {"code": "authentication_unknown", "message": "nope"},
        }).encode()

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized",
                {yoke_handshake.ENGINE_VERSION_HEADER: "2.0.0"},
                io.BytesIO(denial),
            )

        monkeypatch.setattr(
            yoke_transport, "open_no_redirect", fake_urlopen
        )
        response = relay_https(_request(), self._CONN)
        assert response.success is False
        assert capsys.readouterr().err == ""
        assert control_plane_payload.current_server_build().name == "v2.0.0"


class TestLocalHandshakeVersion:
    def test_uses_lockstep_cli_dist_without_probing_engine(self, monkeypatch):
        from yoke_contracts import engine_version as ev

        origins = []
        monkeypatch.setattr(
            ev,
            "_module_origin",
            lambda package: origins.append(package) or (
                f"/site-packages/{package}/__init__.py"
            ),
        )
        monkeypatch.setattr(
            ev,
            "distribution_version_for_module",
            lambda dist, _origin: (
                "2.9.0" if dist == ev.CLIENT_DISTRIBUTION_NAME else "3.0.0"
            ),
        )
        assert ev.local_handshake_version() == "2.9.0"
        assert origins == ["yoke_cli"]

    def test_client_only_install_falls_back_to_cli_dist(self, monkeypatch):
        from yoke_contracts import engine_version as ev

        monkeypatch.setattr(
            ev,
            "_module_origin",
            lambda package: (
                "" if package == "yoke_core" else "/site-packages/yoke_cli/__init__.py"
            ),
        )
        monkeypatch.setattr(
            ev,
            "distribution_version_for_module",
            lambda dist, _origin: (
                "2.9.0" if dist == ev.CLIENT_DISTRIBUTION_NAME else ""
            ),
        )
        assert ev.installed_engine_version() == ""
        assert ev.local_handshake_version() == "2.9.0"

    def test_source_run_ignores_stale_installed_metadata(self, monkeypatch):
        from yoke_contracts import engine_version as ev
        from yoke_contracts import install_binding as binding

        class StaleDistribution:
            version = "99.0.0"

            @staticmethod
            def locate_file(_path):
                return "/unrelated/site-packages"

        monkeypatch.setattr(binding, "_distribution", lambda _dist: StaleDistribution())
        assert ev.local_handshake_version() == ""

    def test_image_build_fallback_is_not_advertised(self, monkeypatch):
        from yoke_contracts import engine_version as ev

        monkeypatch.setattr(
            ev, "installed_engine_version",
            lambda: ev.UNRESOLVED_SCM_FALLBACK_VERSION,
        )
        assert ev.advertised_engine_version(build="abc123def456") == ""
        assert ev.advertised_engine_version(build="") == (
            ev.UNRESOLVED_SCM_FALLBACK_VERSION
        )


class TestServerHandshakeObservation:
    _CONN = HttpsConnection(api_url="https://api.example", token="tok-123")

    def test_success_response_records_advertised_version(self, monkeypatch):
        class _Response:
            headers = {yoke_handshake.ENGINE_VERSION_HEADER: "2.0.0"}

            def read(self, *_args, **_kwargs):
                return json.dumps({
                    "success": True,
                    "function": "events.query.run",
                    "version": "v1",
                }).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        monkeypatch.setattr(
            yoke_transport, "open_no_redirect", lambda req, timeout=None: _Response()
        )
        handshake = ServerHandshake()
        relay_https(_request(), self._CONN, handshake=handshake)
        assert handshake.engine_version == "2.0.0"

    def test_error_response_records_advertised_version(self, monkeypatch):
        denial = json.dumps({
            "success": False,
            "error": {"code": "function_not_registered", "message": "nope"},
        }).encode()

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url,
                404,
                "Not Found",
                {yoke_handshake.ENGINE_VERSION_HEADER: "2.0.0"},
                io.BytesIO(denial),
            )

        monkeypatch.setattr(yoke_transport, "open_no_redirect", fake_urlopen)
        handshake = ServerHandshake()
        relay_https(_request(), self._CONN, handshake=handshake)
        assert handshake.engine_version == "2.0.0"

    def test_absent_header_leaves_handshake_empty(self, monkeypatch):
        class _Response:
            headers = {}

            def read(self, *_args, **_kwargs):
                return json.dumps({
                    "success": True,
                    "function": "events.query.run",
                    "version": "v1",
                }).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        monkeypatch.setattr(
            yoke_transport, "open_no_redirect", lambda req, timeout=None: _Response()
        )
        handshake = ServerHandshake()
        relay_https(_request(), self._CONN, handshake=handshake)
        assert handshake.engine_version == ""
