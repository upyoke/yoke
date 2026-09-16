"""session_ci_wait.resolve is registered and authorized on HTTPS dispatch."""

from __future__ import annotations

from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.fixtures.session_holdings import insert_session
from yoke_core.api.main import app
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.function_authz_product_scopes import PRODUCT_AUTHZ_BY_ID
from yoke_core.domain.function_authz_scope import classify, permission_key_for
from yoke_core.domain.function_authz_types import ACTOR_SESSION
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.session_ci_wait_schema import ensure_session_ci_wait_schema
from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests

FUNCTION_ID = "session_ci_wait.resolve"
SESSION = "s-owner-ci-wait"
RUN_ID = "35129797098"


def _envelope(session_id: str) -> dict:
    return {
        "function": FUNCTION_ID,
        "version": "v1",
        "actor": {"session_id": session_id},
        "target": {"kind": "global"},
        "payload": {"run_id": RUN_ID, "conclusion": "success"},
    }


def _wait_row(conn):
    return conn.execute(
        "SELECT conclusion, notified_at FROM session_ci_run_waits "
        "WHERE session_id = %s AND run_id = %s",
        (SESSION, RUN_ID),
    ).fetchone()


def test_https_owner_resolves_wait_and_other_actor_cannot(monkeypatch):
    """POST /v1/functions/call mutates only the authenticated owner's wait."""
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

        with test_database() as conn:
            owner = mint_api_auth_context(conn)
            insert_session(conn, SESSION)
            conn.execute(
                "UPDATE harness_sessions SET actor_id = %s WHERE session_id = %s",
                (owner.actor_id, SESSION),
            )
            ensure_session_ci_wait_schema(conn)
            conn.execute(
                "INSERT INTO session_ci_run_waits "
                "(session_id,project_id,repo,run_id,head_sha,kind,"
                "continue_command,created_at) "
                "VALUES (%s,%s,%s,%s,%s,'selection',%s,%s)",
                (
                    SESSION,
                    owner.project_id,
                    "acme/widgets",
                    RUN_ID,
                    "ab" * 20,
                    "yoke watch pytest --impacted main --bounded",
                    "2026-09-16T18:00:00Z",
                ),
            )
            other_id = seed_human_actor(conn, "other")
            other_token = mint_token(conn, actor_id=other_id, name="other-actor")
            conn.commit()

            client = TestClient(app)
            try:
                listed = client.get(
                    "/v1/functions/registry", headers=owner.headers
                )
                assert listed.status_code == 200
                ids = [row["function_id"] for row in listed.json()["functions"]]
                assert FUNCTION_ID in ids
                schema = client.get(
                    f"/v1/functions/schema/{FUNCTION_ID}",
                    headers=owner.headers,
                )
                assert schema.status_code == 200
                assert "properties" in schema.json()

                denied = client.post(
                    "/v1/functions/call",
                    json=_envelope(SESSION),
                    headers={"Authorization": f"Bearer {other_token.raw_token}"},
                )
                assert denied.status_code == 403, denied.text
                assert denied.json()["error"]["code"] == "actor_id_mismatch"
                pending = _wait_row(conn)
                assert pending["conclusion"] == ""
                assert pending["notified_at"] is None

                posted = client.post(
                    "/v1/functions/call",
                    json=_envelope(SESSION),
                    headers=owner.headers,
                )
                assert posted.status_code == 200, posted.text
                body = posted.json()
                assert body["success"] is True
                assert body["error"] is None
                assert body["result"]["resolved"] is True
                assert body["result"]["session_id"] == SESSION
                assert body["result"]["run_id"] == RUN_ID
                resolved = _wait_row(conn)
                assert resolved["conclusion"] == "success"
                assert resolved["notified_at"]
            finally:
                client.close()
    finally:
        reset_registry_for_tests()
