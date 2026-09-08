"""Handler coverage for the hosted path-boundary proof functions."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import path_claim_boundary_gate_proof as proof_module
from yoke_core.domain.handlers.claims_path_boundary import (
    handle_boundary_context,
    handle_boundary_observe,
    handle_boundary_prove,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.path_claim_boundary_gate_proof import BoundaryProofError
from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests


@pytest.fixture
def db(tmp_path):
    with init_test_db(tmp_path) as db_path:
        yield db_path


def _request(function: str, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="worker", session_id="session-1"),
        target=TargetRef(kind="item", item_id=7777),
        payload=payload or {},
    )


def test_context_handler_returns_authoritative_context(db, monkeypatch):
    expected = {"item_id": 7777, "claims": [{"claim_id": 8}]}
    monkeypatch.setattr(
        proof_module,
        "boundary_context",
        lambda _conn, item_id: {**expected, "item_id": item_id},
    )
    outcome = handle_boundary_context(_request("claims.path.boundary_context"))
    assert outcome.primary_success
    assert outcome.result_payload == {"context": expected}


def test_prove_handler_binds_actor_session(db, monkeypatch):
    observed = {}

    def _record(_conn, *, item_id, session_id, proof):
        observed.update(
            item_id=item_id,
            session_id=session_id,
            proof=proof,
        )
        return {
            "rung_id": "remote_integration_ref",
            "lane": {"commit_sha": "a" * 40},
        }

    monkeypatch.setattr(proof_module, "record_boundary_proof", _record)
    outcome = handle_boundary_prove(
        _request("claims.path.boundary_prove", {"proof": {"kind": "proof"}})
    )
    assert outcome.primary_success
    assert observed == {
        "item_id": 7777,
        "session_id": "session-1",
        "proof": {"kind": "proof"},
    }
    assert outcome.result_payload["lane_commit_sha"] == "a" * 40


def test_observe_handler_builds_local_proof(monkeypatch):
    proof = {"kind": "proof"}
    monkeypatch.setattr(
        proof_module,
        "build_local_boundary_proof",
        lambda context, repo_path: {
            **proof,
            "item_id": context["item_id"],
            "repo_path": repo_path,
        },
    )
    request = FunctionCallRequest(
        function="claims.path.boundary_observe",
        actor=ActorContext(actor_id="worker", session_id="session-1"),
        target=TargetRef(kind="global"),
        payload={"context": {"item_id": 7777}, "repo_path": "/lane"},
    )
    outcome = handle_boundary_observe(request)
    assert outcome.primary_success
    assert outcome.result_payload == {
        "proof": {"kind": "proof", "item_id": 7777, "repo_path": "/lane"}
    }


def test_prove_handler_returns_named_refusal(db, monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise BoundaryProofError("coverage changed")

    monkeypatch.setattr(proof_module, "record_boundary_proof", _refuse)
    outcome = handle_boundary_prove(
        _request("claims.path.boundary_prove", {"proof": {"kind": "proof"}})
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "boundary_proof_refused"
    assert outcome.error.message == "coverage changed"


def test_boundary_functions_have_claimed_transport_contracts():
    reset_registry_for_tests()
    try:
        register_all_handlers()
        context = lookup("claims.path.boundary_context")
        observe = lookup("claims.path.boundary_observe")
        prove = lookup("claims.path.boundary_prove")
        assert context is not None and context.adapter_status == "internal"
        assert observe is not None and observe.adapter_status == "internal"
        assert observe.claim_required_kind is None
        assert prove is not None and prove.adapter_status == "live"
        assert context.claim_required_kind == prove.claim_required_kind == "item"
    finally:
        reset_registry_for_tests()
