"""Authenticated self-host-only universe export route coverage."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse

from yoke_contracts.server_mode import SERVER_MODE_ENV, SERVER_MODE_SELF_HOST
from yoke_core.api.http_auth import AUTH_STATE_ATTR, HttpAuthContext
from yoke_core.api.routes import universe_portability as route
from yoke_core.domain.actor_permissions import PermissionDenied


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        pass


def _request() -> Request:
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/v1/universe/export",
        "headers": [],
    })
    setattr(
        request.state,
        AUTH_STATE_ATTR,
        HttpAuthContext(token_id=7, actor_id=11, token_name="admin"),
    )
    return request


def test_route_is_hidden_outside_self_host(monkeypatch):
    monkeypatch.delenv(SERVER_MODE_ENV, raising=False)
    response = route.download_self_host_universe(_request())
    assert response.status_code == 404


def test_route_requires_org_admin(monkeypatch):
    monkeypatch.setenv(SERVER_MODE_ENV, SERVER_MODE_SELF_HOST)
    monkeypatch.setattr(route.db_helpers, "connect", _Connection)

    def deny(*_args, **_kwargs):
        raise PermissionDenied("org admin required")

    monkeypatch.setattr(route, "require_control_plane_permission", deny)
    response = route.download_self_host_universe(_request())
    assert response.status_code == 403


def test_route_exports_server_authority_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv(SERVER_MODE_ENV, SERVER_MODE_SELF_HOST)
    monkeypatch.setattr(route.db_helpers, "connect", _Connection)
    monkeypatch.setattr(route, "require_control_plane_permission", lambda *_a, **_k: None)
    monkeypatch.setattr(route.db_backend, "resolve_pg_dsn", lambda: "postgresql://private")
    def make_temp(**_kwargs):
        directory = tmp_path / "export"
        directory.mkdir()
        return str(directory)

    monkeypatch.setattr(route.tempfile, "mkdtemp", make_temp)

    def export_universe(*, dsn, out):
        assert dsn == "postgresql://private"
        directory = Path(out)
        directory.mkdir(parents=True, exist_ok=True)
        artifact = directory / "acme-universe.tar"
        artifact.write_bytes(b"archive")
        return {
            "artifact": str(artifact),
            "format": "universe-tar",
            "org": "acme",
            "sha256": "b" * 64,
        }

    monkeypatch.setattr(route.universe_export, "export_universe", export_universe)
    response = route.download_self_host_universe(_request())
    assert isinstance(response, FileResponse)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-yoke-universe-org"] == "acme"
    assert Path(response.path).read_bytes() == b"archive"
    asyncio.run(response.background())
    assert not (tmp_path / "export").exists()
