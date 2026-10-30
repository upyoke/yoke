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
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/universe/export",
            "headers": [],
        }
    )
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
    monkeypatch.setattr(
        route, "require_control_plane_permission", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        route.db_backend, "resolve_pg_dsn", lambda: "postgresql://private"
    )

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


def test_paused_server_refuses_mutation_and_allows_explicit_resume(
    monkeypatch, tmp_path
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from yoke_core.api.universe_pause_admission import install
    from yoke_core.domain import universe_source_pause

    monkeypatch.setenv(SERVER_MODE_ENV, SERVER_MODE_SELF_HOST)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    dsn = "host=localhost dbname=paused-source"
    monkeypatch.setattr(route.db_backend, "resolve_pg_dsn", lambda: dsn)
    marker = universe_source_pause._marker(dsn)
    marker.parent.mkdir(parents=True)
    marker.write_text("{}")
    app = FastAPI()
    writes = []

    @app.post("/v1/items")
    def mutate():
        writes.append("mutated")
        return {"ok": True}

    @app.post("/v1/universe/resume")
    def resume():
        universe_source_pause.require_running(dsn)
        marker.unlink()
        return {"resumed": True}

    install(app)
    with TestClient(app) as client:
        refused = client.post("/v1/items")
        assert refused.status_code == 503
        assert refused.json()["error"]["code"] == "universe_source_paused"
        assert "universe resume" in refused.json()["error"]["message"]
        assert writes == []
        from concurrent.futures import ThreadPoolExecutor

        with (
            universe_source_pause.operation(dsn),
            ThreadPoolExecutor(max_workers=1) as competing,
        ):
            busy = competing.submit(client.post, "/v1/universe/resume").result(
                timeout=5
            )
            assert busy.status_code == 409
            assert busy.json()["error"]["code"] == "universe_source_busy"
            assert marker.exists()
        assert client.post("/v1/universe/resume").json() == {"resumed": True}
        assert client.post("/v1/items").json() == {"ok": True}
        assert writes == ["mutated"]


def test_resume_requires_org_admin(monkeypatch):
    monkeypatch.setenv(SERVER_MODE_ENV, SERVER_MODE_SELF_HOST)
    monkeypatch.setattr(route.db_helpers, "connect", _Connection)

    def deny(*_args, **_kwargs):
        raise PermissionDenied("org admin required")

    monkeypatch.setattr(route, "require_control_plane_permission", deny)
    response = route.resume_self_host_universe(_request())
    assert response.status_code == 403


def test_paused_export_refuses_ephemeral_server_state(monkeypatch):
    monkeypatch.setenv(SERVER_MODE_ENV, SERVER_MODE_SELF_HOST)
    monkeypatch.delenv("YOKE_MACHINE_HOME", raising=False)
    monkeypatch.setattr(route.db_helpers, "connect", _Connection)
    monkeypatch.setattr(
        route, "require_control_plane_permission", lambda *_a, **_k: None
    )
    response = route.download_self_host_universe(_request(), pause_source=True)
    assert response.status_code == 409
    assert b"universe_pause_storage_unavailable" in response.body
    assert b"protect-existing" in response.body
