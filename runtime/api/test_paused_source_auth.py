"""A restarted paused self-host authenticates on its frozen copy without writes."""

import json

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb
from yoke_core.api import http_auth, server_entrypoint, universe_pause_admission
from yoke_core.api.routes.universe_portability import router
from yoke_core.domain import api_tokens, db_backend, universe_source_pause as pause
from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    grant_actor_org_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.org_schema import seed_default_org


def test_paused_restart_keeps_auth_checks_and_resume_uses_original(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    monkeypatch.setenv("YOKE_SERVER_MODE", "self-host")
    with pg_testdb.test_database() as source:
        seed_roles_and_permissions(source)
        actor = seed_human_actor(source, "source administrator")
        grant_actor_org_role(
            source,
            actor_id=actor,
            org_id=seed_default_org(source),
            role_name=ROLE_ADMIN,
        )
        active = api_tokens.mint_token(source, actor_id=actor, name="active")
        revoked = api_tokens.mint_token(source, actor_id=actor, name="revoked")
        api_tokens.revoke_token(source, token_id=revoked.token_id)
        dsn = db_backend.resolve_pg_dsn()
        pause.pause(dsn)
        state = json.loads(pause._marker(dsn).read_text())["database_pause"]
        app = FastAPI()

        @app.middleware("http")
        async def authenticate(request, call_next):
            auth = http_auth.authenticate_request(request)
            if isinstance(auth, JSONResponse):
                return auth
            setattr(request.state, http_auth.AUTH_STATE_ATTR, auth)
            return await call_next(request)

        app.include_router(router, prefix="/v1")
        universe_pause_admission.install(app)
        prepared = []

        def prepare(**_kwargs):
            with db_backend.connect_psycopg(dsn) as conn:
                prepared.append(conn.info.dbname)
                conn.execute("CREATE TABLE resumed_preparation (value text)")

        monkeypatch.setattr(server_entrypoint, "ensure_core_schema", prepare)
        monkeypatch.setattr(
            server_entrypoint, "ensure_permission_catalog", lambda **_k: None
        )
        try:
            with TestClient(app) as client:
                endpoint = "/v1/universe/export?pause_source=true"
                assert client.get(endpoint).status_code == 401
                assert (
                    client.get(
                        endpoint,
                        headers={"Authorization": f"Bearer {revoked.raw_token}"},
                    ).status_code
                    == 401
                )
                headers = {"Authorization": f"Bearer {active.raw_token}"}
                exported = client.get(endpoint, headers=headers)
                assert exported.status_code == 200, exported.text
                assert exported.headers["x-yoke-universe-writers-stopped"] == "true"
                with pause.pause_owner(), db_backend.connect_psycopg(dsn) as clone:
                    assert clone.info.dbname == state["copy"]
                    assert (
                        clone.execute(
                            "SELECT last_used_at FROM api_tokens WHERE id=%s",
                            (active.token_id,),
                        ).fetchone()[0]
                        is None
                    )
                resumed = client.post("/v1/universe/resume", headers=headers)
                assert resumed.status_code == 200, resumed.text
                assert prepared == [state["name"]]
                assert not pause.is_paused(dsn)
        finally:
            if pause.is_paused(dsn):
                pause.resume(dsn)
