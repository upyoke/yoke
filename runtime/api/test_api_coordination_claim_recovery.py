"""Authenticated HTTP recovery for a stranded coordination claim."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.domain.coordination_claim_test_support import seed_session
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import SCHEMA_DDL, apply_fixture_ddl
from runtime.api.test_api_helpers import _install_overrides
from yoke_core.api.main import app
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.coordination_claims import acquire, active_claim
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.work_claim_targets import make_deploy_serialization_target
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


def _apply_schema() -> None:
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, SCHEMA_DDL)
    finally:
        conn.close()


@pytest.fixture
def recovery_api(tmp_path):
    with ExitStack() as stack:
        db_path = stack.enter_context(
            init_test_db(tmp_path, apply_schema=_apply_schema)
        )
        stack.enter_context(_install_overrides(db_path))
        conn = connect_test_db(db_path)
        auth = mint_api_auth_context(conn)
        seed_session(conn, "stranded-holder", auth.project_id)
        target = make_deploy_serialization_target(auth.project_id, "yoke")
        claim = acquire(conn, target, "stranded-holder")
        reset_registry_for_tests()
        register_all_handlers()
        stack.enter_context(patch.object(events_module, "emit_event"))
        stack.enter_context(
            patch.object(dispatch_module, "_idempotency_lookup", return_value=None)
        )
        stack.enter_context(
            patch(
                "yoke_core.domain.coordination_claims_operator._emit_operator_release"
            )
        )
        client = stack.enter_context(TestClient(app))
        try:
            yield client, conn, auth, target, claim
        finally:
            reset_registry_for_tests()
            conn.close()


def _envelope(claim, *, session_id: str = "") -> dict:
    return {
        "function": "claims.coordination_claim.operator_release",
        "actor": {"actor_id": "untrusted", "session_id": session_id},
        "target": {"kind": "global"},
        "payload": {
            "project_id": "yoke",
            "key": "DEPLOY:yoke",
            "claim_id": claim.id,
            "holder_session_id": "stranded-holder",
            "reason": "confirmed deployment pipeline settled",
        },
    }


def test_signed_in_human_owner_can_release_over_http(recovery_api) -> None:
    client, conn, auth, target, claim = recovery_api

    response = client.post(
        "/v1/functions/call",
        json=_envelope(claim),
        headers=auth.headers,
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["operator_actor_id"] == auth.actor_id
    assert active_claim(conn, target) is None


@pytest.mark.parametrize("session_id", ("manual-agent", "launched-agent"))
def test_harness_session_cannot_use_human_recovery(
    recovery_api, session_id: str
) -> None:
    client, conn, auth, target, claim = recovery_api

    response = client.post(
        "/v1/functions/call",
        json=_envelope(claim, session_id=session_id),
        headers=auth.headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_operator_required"
    assert active_claim(conn, target) is not None
