"""Public proof round trips and in-process lifecycle envelope isolation."""

from contextlib import closing
from unittest.mock import patch

import pytest
from psycopg.errors import LockNotAvailable

from runtime.api.domain._path_claims_test_helpers import HOLDER_SESSION_ID, local_human
from runtime.api.domain.test_path_claim_boundary_gate_proof import (
    _remote_from,
    _seed_proof_case,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.schema_apply import apply_canonical_schema
from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_contracts.public_item_contract import public_item_request_error
from yoke_core.domain.gate_satisfier_stamp import read_rungs
from yoke_core.domain.path_claim_boundary_gate_proof import record_boundary_proof
from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings
from yoke_core.domain.actor_permissions import grant_actor_project_role, ROLE_OWNER
from yoke_core.domain.projects_restart_schema import create_project_registry_tables
from yoke_core.domain.universe_levels import create_universe_settings_table
from yoke_core.domain.workflow_execution_instructions_schema import (
    ensure_workflow_execution_instructions_schema,
)
from yoke_core.domain.yoke_function_dispatch import dispatch


pytest_plugins = ("runtime.api.domain.test_path_claims_gate_boundary",)
ITEM_ID = 7777
ITEM_REF = f"YOK-{ITEM_ID}"


@pytest.fixture
def local_dispatch(monkeypatch):
    monkeypatch.setenv("YOKE_SESSION_ID", HOLDER_SESSION_ID)
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection", lambda **_kwargs: None
    )

    def call(function, target=None, payload=None):
        response = call_dispatcher(
            function_id=function,
            target=target or TargetRef(kind="item", public_ref=ITEM_REF),
            payload=payload or {},
            actor=ActorContext(session_id=HOLDER_SESSION_ID),
            _local_dispatch=dispatch,
        )
        assert response.success, response.model_dump()
        return response.result

    return call


def test_public_boundary_context_observe_prove_round_trip(
    project_repo, real_db, monkeypatch, local_dispatch
):
    _claim, lane, _context, _proof = _seed_proof_case(project_repo, real_db)
    context = local_dispatch("claims.path.boundary_context")["context"]
    assert context["public_ref"] == ITEM_REF
    assert context["lane"]["public_ref"] == ITEM_REF
    assert "item_id" not in context
    assert "item_id" not in context["lane"]
    proof = local_dispatch(
        "claims.path.boundary_observe",
        TargetRef(kind="global"),
        {"context": context, "repo_path": str(lane)},
    )["proof"]
    assert proof["public_ref"] == ITEM_REF
    assert proof["lane"] == context["lane"]
    monkeypatch.setattr(
        "yoke_core.domain.path_claim_boundary_proof_validation._remote_heads",
        lambda *_args: _remote_from(proof),
    )
    result = local_dispatch("claims.path.boundary_prove", payload={"proof": proof})
    assert result["public_ref"] == ITEM_REF
    with closing(connect_test_db(real_db)) as conn:
        assert read_rungs(conn, ITEM_ID)[0]["rung_id"] == proof["rung_id"]


@pytest.mark.parametrize("source_precondition", [False, True])
def test_in_process_detail_then_path_claimed_lifecycle_transition(
    project_repo, real_db, monkeypatch, local_dispatch, source_precondition
):
    with closing(connect_test_db(real_db)) as conn:
        create_project_registry_tables(conn)
        create_universe_settings_table(conn)
        apply_canonical_schema(conn)
        ensure_workflow_execution_instructions_schema(conn)
        grant_actor_project_role(
            conn, actor_id=local_human(conn), project_id=1, role_name=ROLE_OWNER
        )
    _seed_proof_case(project_repo, real_db)
    with closing(connect_test_db(real_db)) as conn:
        conn.execute(
            "UPDATE items SET status = 'reviewing-implementation' WHERE id = %s",
            (ITEM_ID,),
        )
        conn.commit()
    # This fixture isolates the boundary gate while the real lifecycle handler
    # and status writer execute against the path-claimed item and real checkout.
    monkeypatch.setattr(
        "yoke_core.domain.backlog_authoritative_status_gate.select_stage_gates",
        lambda *_args, **_kwargs: ({"id": "path_claim_boundary"},),
    )
    target = TargetRef(kind="item", public_ref=ITEM_REF)
    local_dispatch("items.detail.get", target)
    assert target.item_id is None
    payload = {"target_status": "reviewed-implementation"}
    if source_precondition:
        payload["source_status"] = "reviewing-implementation"
    result = local_dispatch("lifecycle.transition.execute", target, payload)
    assert result["to_status"] == "reviewed-implementation"
    assert target.item_id is None
    with closing(connect_test_db(real_db)) as conn:
        assert (
            conn.execute(
                "SELECT status FROM items WHERE id = %s", (ITEM_ID,)
            ).fetchone()[0]
            == "reviewed-implementation"
        )
        assert read_rungs(conn, ITEM_ID)[0]["target_status"] == result["to_status"]


def test_resolving_typed_request_keeps_caller_payload_public():
    from yoke_contracts.api.function_call import FunctionCallRequest
    from yoke_core.domain.yoke_function_dispatch import _coerce_request
    from yoke_core.domain.yoke_function_dispatch_target import resolve_request_item_refs
    from pydantic import BaseModel

    class RequestBody(BaseModel):
        item_id: int

    request = FunctionCallRequest(
        function="claims.path.boundary_context",
        actor=ActorContext(session_id=HOLDER_SESSION_ID),
        target=TargetRef(kind="item", public_ref=ITEM_REF),
        payload={"public_ref": ITEM_REF},
    )
    with (
        patch("yoke_core.domain.db_helpers.connect"),
        patch(
            "yoke_core.domain.item_ref_resolution.resolve_item_ref",
            return_value=ITEM_ID,
        ),
    ):
        resolved, error = _coerce_request(request)
        assert error is None
        assert resolve_request_item_refs(resolved, RequestBody) is None
    assert resolved.target.item_id == ITEM_ID
    assert resolved.payload == {"item_id": ITEM_ID}
    assert request.payload == {"public_ref": ITEM_REF}
    assert request.target.item_id is None
    assert public_item_request_error(request) is None


def test_boundary_stamp_does_not_wait_on_own_status_transaction(
    project_repo, real_db, monkeypatch
):
    _claim, _lane, _context, proof = _seed_proof_case(project_repo, real_db)
    monkeypatch.setattr(
        "yoke_core.domain.path_claim_boundary_proof_validation._remote_heads",
        lambda *_args: _remote_from(proof),
    )
    with (
        closing(connect_test_db(real_db)) as writer,
        closing(connect_test_db(real_db)) as gate,
    ):
        lock_item_workflow_bindings(writer, [ITEM_ID])
        gate.execute("SET lock_timeout = '1s'")
        record_boundary_proof(
            gate, item_id=ITEM_ID, session_id=HOLDER_SESSION_ID, proof=proof
        )
        assert read_rungs(gate, ITEM_ID)[0]["rung_id"] == proof["rung_id"]
        # Referencing the immutable key may proceed; a competing item writer
        # still waits until the status transaction releases its lock.
        with pytest.raises(LockNotAvailable):
            gate.execute(
                "UPDATE items SET title = 'competing writer' WHERE id = %s",
                (ITEM_ID,),
            )
