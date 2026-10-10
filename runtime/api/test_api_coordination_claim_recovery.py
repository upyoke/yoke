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
from yoke_core.domain.work_claim_targets import (
    make_migration_serialization_target,
    make_qa_admission_target,
)
from yoke_contracts.coordination_claim_recovery import operator_release_command
from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallResponse
import shlex
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


def _apply_schema() -> None:
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, SCHEMA_DDL)
    finally:
        conn.close()


@pytest.fixture(params=("migration", "qa_host"))
def recovery_api(tmp_path, request):
    with ExitStack() as stack:
        db_path = stack.enter_context(
            init_test_db(tmp_path, apply_schema=_apply_schema)
        )
        stack.enter_context(_install_overrides(db_path))
        conn = connect_test_db(db_path)
        auth = mint_api_auth_context(conn)
        seed_session(conn, "stranded-holder", auth.project_id)
        target = (
            make_qa_admission_target("test-mac")
            if request.param == "qa_host"
            else make_migration_serialization_target(auth.project_id, "core", 7)
        )
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
            **({"project_id": "yoke"} if claim.project_id is not None else {}),
            "key": claim.key,
            "claim_id": claim.id,
            "holder_session_id": "stranded-holder",
            "reason": "confirmed the rehearsal driver exited",
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


def test_printed_recovery_command_releases_exact_row_and_audits_reason(recovery_api):
    client, conn, auth, target, claim = recovery_api
    reason = "stale holder confirmed after reviewing machine"
    command = operator_release_command(
        claim.project_id,
        claim.key,
        claim_id=claim.id,
        holder_session_id=claim.session_id,
        reason=reason,
    )
    if claim.project_id is None:
        assert "--project" not in command

    def dispatch(**kwargs):
        response = client.post(
            "/v1/functions/call",
            json={
                "function": kwargs["function_id"],
                "actor": {"session_id": ""},
                "target": {"kind": "global"},
                "payload": kwargs["payload"],
            },
            headers=auth.headers,
        )
        assert response.status_code == 200, response.json()
        assert response.json()["result"]["operator_actor_id"] == auth.actor_id
        return FunctionCallResponse.model_validate(response.json())

    with (
        patch("yoke_cli.commands._helpers.call_dispatcher", side_effect=dispatch),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
    ):
        assert cli_main(shlex.split(command)[1:]) == 0
    assert active_claim(conn, target) is None
    row = conn.execute(
        "SELECT release_reason_intent FROM work_claims WHERE id=%s",
        (claim.id,),
    ).fetchone()
    assert row[0] == f"operator-override: {reason}"


@pytest.mark.parametrize("project", (None, "externalwebapp", "0"))
def test_machine_key_list_ignores_project_and_resolves_holder_authority(
    recovery_api, project
):
    client, conn, auth, target, claim = recovery_api
    if claim.project_id is not None:
        pytest.skip("machine-scoped listing")
    payload = {"key": claim.key, "active_only": True}
    if project is not None:
        payload["project_id"] = project
    response = client.post(
        "/v1/functions/call",
        json={
            "function": "claims.coordination_claim.list",
            "actor": {"session_id": ""},
            "target": {"kind": "global"},
            "payload": payload,
        },
        headers=auth.headers,
    )
    assert response.status_code == 200, response.json()
    assert [row["id"] for row in response.json()["result"]["claims"]] == [claim.id]


@pytest.mark.parametrize(
    "field,value", (("claim_id", -1), ("holder_session_id", "other-holder"))
)
def test_operator_recovery_refuses_changed_claim_or_holder(recovery_api, field, value):
    client, conn, auth, target, claim = recovery_api
    envelope = _envelope(claim)
    envelope["payload"][field] = value
    response = client.post("/v1/functions/call", json=envelope, headers=auth.headers)
    assert response.json()["success"] is False
    assert active_claim(conn, target).id == claim.id
