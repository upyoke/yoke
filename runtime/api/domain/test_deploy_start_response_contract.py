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

        def client_call(**kwargs):
            return dispatcher.call_dispatcher(**kwargs, _local_dispatch=dispatch)

        monkeypatch.setattr(control_plane, "call_dispatcher", client_call)
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
