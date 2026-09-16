"""session_ci_wait.resolve is registered on the HTTPS function-call API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import SCHEMA_DDL, apply_fixture_ddl
from runtime.api.test_api_helpers import _install_overrides
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.api.main import app
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.function_authz_product_scopes import PRODUCT_AUTHZ_BY_ID
from yoke_core.domain.function_authz_scope import classify, permission_key_for
from yoke_core.domain.function_authz_types import ACTOR_SESSION
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests

FUNCTION_ID = "session_ci_wait.resolve"


def _apply_schema() -> None:
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, SCHEMA_DDL)
    finally:
        conn.close()


def test_https_dispatch_registers_session_ci_wait_resolve(tmp_path, monkeypatch):
    """The public API loads this id the same way a serving HTTPS process does.

    FastAPI lifespan and ``dispatch`` both call ``register_all_handlers``;
    ``POST /v1/functions/call`` is ``dispatch``. A missing CLI adapter is
    expected (``adapter_status=internal``) and is not an unregistered
    function.
    """
    monkeypatch.setattr(events_module, "emit_event", lambda *_a, **_k: None)
    monkeypatch.setattr(dispatch_module, "_idempotency_lookup", lambda *_a, **_k: None)
    reset_registry_for_tests()
    register_all_handlers()
    try:
        entry = lookup(FUNCTION_ID)
        assert entry is not None
        assert entry.adapter_status == "internal"
        spec = classify(
            FUNCTION_ID,
            side_effects=bool(entry.side_effects),
            project_permission=permission_key_for(entry),
        )
        assert spec.scope == ACTOR_SESSION
        assert PRODUCT_AUTHZ_BY_ID[FUNCTION_ID].scope == ACTOR_SESSION

        dispatched = dispatch(
            FunctionCallRequest(
                function=FUNCTION_ID,
                actor=ActorContext(session_id="s1"),
                target=TargetRef(kind="global"),
                payload={"run_id": "35129797098", "conclusion": "success"},
            )
        )
        assert dispatched.error is None or dispatched.error.code != (
            "function_not_registered"
        )

        with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
            with _install_overrides(db_path):
                conn = connect_test_db(db_path)
                try:
                    auth = mint_api_auth_context(conn)
                finally:
                    conn.close()
                client = TestClient(app)
                try:
                    client.headers.update(auth.headers)
                    listed = client.get("/v1/functions/registry")
                    assert listed.status_code == 200
                    ids = [row["function_id"] for row in listed.json()["functions"]]
                    assert FUNCTION_ID in ids
                    schema = client.get(f"/v1/functions/schema/{FUNCTION_ID}")
                    assert schema.status_code == 200
                    assert "properties" in schema.json()
                    posted = client.post(
                        "/v1/functions/call",
                        json={
                            "function": FUNCTION_ID,
                            "version": "v1",
                            "actor": {"session_id": "s1"},
                            "target": {"kind": "global"},
                            "payload": {
                                "run_id": "35129797098",
                                "conclusion": "success",
                            },
                        },
                    )
                    error = (posted.json().get("error") or {})
                    assert error.get("code") != "function_not_registered"
                    assert posted.status_code != 404
                finally:
                    client.close()
    finally:
        reset_registry_for_tests()
