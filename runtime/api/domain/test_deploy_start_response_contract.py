"""A deploy start preserves the server's digest-bound containment questions."""

from contextlib import nullcontext

import pytest

from runtime.api.domain.test_release_delivery_live_visibility import (
    ITEM_ID,
    _LocalAnswer,
    _open_item,
    _stage_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_cli.transport import dispatcher, https as https_transport
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import (
    deploy_pipeline_control_plane as control_plane,
    deploy_pipeline_run_updates,
    deployment_run_contained_items as containment,
    yoke_function_dispatch as server_dispatch,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.json_helper import loads_text


@pytest.mark.parametrize(
    "transport,compose", [("https", False), ("https", True), ("local", True)]
)
@pytest.mark.parametrize("read", ["context", "containment_basis"])
def test_start_attests_dispatched_basis_without_rewriting_it(
    monkeypatch, transport, compose, read
):
    monkeypatch.setattr(
        containment, "LocalCheckoutSource", lambda _: _LocalAnswer(True)
    )
    monkeypatch.setattr(dispatcher, "_client_label_overrides", lambda: {})
    monkeypatch.setattr(
        dispatcher.local_github_dispatch,
        "call_with_machine_github_authorization",
        lambda request, dispatch, **_: dispatch(request),
    )
    monkeypatch.setattr(
        server_dispatch, "dispatch_observation", lambda _: nullcontext(lambda _: None)
    )
    monkeypatch.setattr(
        https_transport,
        "resolve_https_connection",
        lambda: object() if transport == "https" else None,
    )
    submitted = []
    with test_database() as conn:
        _open_item(conn)
        _stage_run(conn)
        basis = containment.candidate_containment_basis(conn, "run-stage")
        assert basis["projects"][0]["items"][0]["id"] == ITEM_ID

        def handle(request, **_):
            if request.function in {
                "deployment_runs.execution.context",
                "deployment_runs.execution.containment_basis",
            }:
                result = {"candidate_containment_basis": basis}
            else:
                assert request.function == "deployment_runs.execution.update"
                attestation = request.payload["candidate_containment"]
                submitted.append(attestation)
                assert attestation["basis_digest"] == basis["basis_digest"]
                refusal = cmd_update(
                    "run-stage",
                    "status",
                    "executing",
                    candidate_containment=attestation,
                )
                assert refusal is None
                result = {"updated": True}
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result=result,
            )

        monkeypatch.setattr(server_dispatch, "_dispatch_impl", handle)
        dispatch = server_dispatch.dispatch if compose else handle
        monkeypatch.setattr(
            https_transport,
            "relay_https",
            lambda request, _connection, **_: dispatch(request),
        )

        received = (
            control_plane.execution_context("run-stage")["candidate_containment_basis"]
            if read == "context"
            else control_plane.containment_basis("run-stage")
        )
        assert received == basis
        deploy_pipeline_run_updates.start_run("run-stage", received, "/repo")
        assert submitted[0]["items"] == [{"id": ITEM_ID, "project_id": 1}]
        row = conn.execute(
            "SELECT status,candidate_containment FROM deployment_runs WHERE id=%s",
            ("run-stage",),
        ).fetchone()
        assert row["status"] == "executing"
        assert (
            loads_text(row["candidate_containment"])["items"] == submitted[0]["items"]
        )


@pytest.mark.parametrize("read", ["context", "containment_basis"])
def test_https_start_uses_the_core_facade_without_client_database_authority(
    monkeypatch, read
):
    from yoke_core.domain import db_helpers, db_backend

    def no_client_database(*args, **kwargs):
        raise AssertionError("HTTPS request composition must not open Postgres")

    monkeypatch.setattr(db_helpers, "connect", no_client_database)
    monkeypatch.setattr(db_backend, "connect", no_client_database)
    monkeypatch.setattr(
        containment, "LocalCheckoutSource", lambda _: _LocalAnswer(True)
    )
    monkeypatch.setattr(dispatcher, "_client_label_overrides", lambda: {})
    monkeypatch.setattr(
        dispatcher.local_github_dispatch,
        "call_with_machine_github_authorization",
        lambda request, dispatch, **_: dispatch(request),
    )
    monkeypatch.setattr(https_transport, "resolve_https_connection", lambda: object())
    basis = {
        "basis_digest": "b" * 64,
        "primary_project": "platform",
        "projects": [
            {
                "project_id": 2,
                "project": "platform",
                "candidate_lineage": "c" * 40,
                "items": [{"id": ITEM_ID, "merge_sha": "d" * 40}],
            }
        ],
    }
    requests = []

    def relay(request, _connection, **kwargs):
        requests.append(request)
        if request.function == "deployment_runs.execution.update":
            answer = request.payload["candidate_containment"]
            assert answer["basis_digest"] == basis["basis_digest"]
            assert answer["items"] == [{"id": ITEM_ID, "project_id": 2}]
            result = {"updated": True}
        else:
            result = {"candidate_containment_basis": basis}
        return FunctionCallResponse(
            success=True, function=request.function, version="v1", result=result
        )

    monkeypatch.setattr(https_transport, "relay_https", relay)
    received = (
        control_plane.execution_context("run-stage")["candidate_containment_basis"]
        if read == "context"
        else control_plane.containment_basis("run-stage")
    )
    deploy_pipeline_run_updates.start_run("run-stage", received, "/repo")
    assert len(requests) == 2
    assert requests[-1].target.workflow_run_id == "run-stage"


def test_core_facade_refuses_numeric_selectors_without_database_reads(monkeypatch):
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
    from yoke_core.domain import db_helpers
    from yoke_contracts.api.function_call import ActorContext, TargetRef

    def no_database(*args, **kwargs):
        raise AssertionError("invalid client selectors must not open Postgres")

    monkeypatch.setattr(db_helpers, "connect", no_database)
    for target, payload in [
        (TargetRef(kind="item", item_id=ITEM_ID), {}),
        (TargetRef(kind="item", public_ref=str(ITEM_ID)), {}),
        (TargetRef(kind="global"), {"item_id": ITEM_ID}),
    ]:
        response = call_dispatcher(
            function_id="items.get.run",
            target=target,
            payload=payload,
            actor=ActorContext(actor_id="test", session_id=""),
        )
        assert not response.success
        assert response.error.code in {
            "internal_item_id_forbidden",
            "public_item_ref_required",
        }
