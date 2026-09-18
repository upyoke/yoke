"""Source-checkout skew must follow loaded yoke_cli, not caller cwd."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.transport import https as yoke_transport
from yoke_cli.transport import https_engine_handshake as yoke_handshake
from yoke_cli.transport import source_build_skew as skew
from yoke_cli.transport.https import HttpsConnection, relay_https

from runtime.api.cli.test_yoke_https_engine_handshake import (
    _FakeResponse,
    _ok_envelope,
    _request,
)


def _relay_with_header(monkeypatch, headers: dict):
    def fake_urlopen(req, timeout=None):
        resp = _FakeResponse(_ok_envelope())
        resp.headers = dict(headers)
        return resp

    monkeypatch.setattr(yoke_transport, "open_no_redirect", fake_urlopen)
    response = relay_https(
        _request(),
        HttpsConnection(api_url="https://api.example", token="tok-123"),
    )
    assert response.success is True
    return response


class TestSourceCheckoutCwdIndependence:
    def test_git_comparison_uses_loaded_yoke_checkout_not_cwd(
        self, monkeypatch, tmp_path, capsys,
    ):
        foreign = tmp_path / "caller-app"
        foreign.mkdir()
        monkeypatch.chdir(foreign)
        monkeypatch.setattr(yoke_handshake, "local_handshake_version", lambda: "")
        seen: list[str] = []

        def capture_server(repo_root, *_args, **_kwargs):
            seen.append(repo_root)
            return skew.BuildComparison(skew.EQUAL)

        monkeypatch.setattr(skew, "compare_to_server_build", capture_server)

        _relay_with_header(
            monkeypatch, {yoke_handshake.ENGINE_VERSION_HEADER: "2.0.0"}
        )

        yoke_root = yoke_handshake._loaded_source_checkout()
        assert yoke_root is not None
        assert Path(yoke_root).resolve() != foreign.resolve()
        assert seen == [yoke_root]
        assert capsys.readouterr().err == ""

    def test_missing_source_checkout_does_not_inspect_caller_git(
        self, monkeypatch, tmp_path, capsys,
    ):
        foreign = tmp_path / "caller-app"
        foreign.mkdir()
        monkeypatch.chdir(foreign)
        monkeypatch.setattr(yoke_handshake, "local_handshake_version", lambda: "")
        monkeypatch.setattr(yoke_handshake, "_loaded_source_checkout", lambda: None)

        def boom(*_args, **_kwargs):
            raise AssertionError("caller git must not be inspected")

        monkeypatch.setattr(skew, "compare_to_server_build", boom)

        _relay_with_header(
            monkeypatch, {yoke_handshake.ENGINE_VERSION_HEADER: "2.0.0"}
        )
        assert capsys.readouterr().err == ""

    def test_packaged_client_still_ignores_git_from_foreign_cwd(
        self, monkeypatch, tmp_path, capsys,
    ):
        foreign = tmp_path / "caller-app"
        foreign.mkdir()
        monkeypatch.chdir(foreign)
        monkeypatch.setattr(
            yoke_handshake, "local_handshake_version", lambda: "1.0.0"
        )

        def boom(*_args, **_kwargs):
            raise AssertionError("packaged clients compare versions, not git")

        monkeypatch.setattr(skew, "compare_to_server_build", boom)

        _relay_with_header(
            monkeypatch, {yoke_handshake.ENGINE_VERSION_HEADER: "2.0.0"}
        )
        assert capsys.readouterr().err == ""
