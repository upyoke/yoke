"""An admin-connected candidate coexists with its reachable https sibling.

Split out of test_deploy_pipeline_admin_bootstrap.py so that module stays
under the authored-file line budget. The two admin-bootstrap tests there
prove the halves in isolation (no https reachable at all; an https-only
driver refused by an old build) — this file proves the halves coexist in
one process: the SAME candidate driver holds a direct admin door into the
database while an explicitly named https sibling is also reachable, and
only the new scoped-QA function ids are missing from that sibling's
registry. The pre-existing human-approval stage keeps relaying to that
sibling exactly as before; the new scoped-QA dispatch/resume route locally
instead, and the run's unresolved QA stays correctly unresolved.

The run seed itself lives in
runtime/api/fixtures/deployment_scoped_qa_run_fixture.py: this serving
runtime's own creation-time gate refuses to START a new run against a
schema-2 (QA-stage) flow through ``deployment_runs.create`` at all (a
pre-existing, deliberate gate unrelated to this change), so an
already-admitted, already-frozen run is seeded directly instead — and
still exercises the real ``deploy_pipeline.run_pipeline`` execution path
this test is about.
"""

from __future__ import annotations

import io
import json
import urllib.error

from runtime.api.domain.test_deploy_pipeline_admin_bootstrap import (
    _admin_driver_env,
    serving_plane,  # noqa: F401 - pytest fixture re-export
)
from runtime.api.domain.test_deploy_pipeline_https_execution import (
    FLOW,
    LINEAGE,
    PROJECT,
    _decision_request_id,
    _invoke,
    _RelayResponse,
    _replace_flow,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    create_smoke_plan,
    seed_frozen_scoped_qa_run,
)
from yoke_cli.transport import https as https_transport
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import deploy_pipeline
from yoke_core.domain.deployment_qa_stage_dispatch import (
    DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
)
from yoke_core.domain.deployment_qa_stage_resume import (
    RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION,
)
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)

ITEM_ID = 9201
RUN_ID = "run-mixed-build-901"

_STAGES = [
    {
        "name": "preflight",
        "step_runner": "auto",
        "stage_kind": "execution",
        "scope": "run",
    },
    {
        "name": "approve-deploy",
        "step_runner": "human-approval",
        "stage_kind": "execution",
        "scope": "run",
        "approvals": {"roles": ["owner"], "actors": []},
    },
    {
        "name": "deploy",
        "step_runner": "auto",
        "stage_kind": "execution",
        "scope": "run",
    },
    {
        "name": "item-qa",
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": "item",
        "target": {"kind": "run_preview", "source_stage": "deploy"},
        "cases": {"plan_id": 0, "case_keys": ["command-smoke"]},
        "verdict": {"mode": "agent_only"},
    },
    {
        "name": "complete",
        "step_runner": "auto",
        "stage_kind": "execution",
        "scope": "run",
    },
]


def _install_named_serving_sibling(monkeypatch, plane) -> list[str]:
    """An https sibling reachable only by its explicit env name, "prod".

    Unlike test_deploy_pipeline_https_execution._install_test_https (an
    ambient, always-on https connection), this candidate's own ambient
    connection is the local admin door: call_dispatcher with no explicit
    relay_env must keep resolving to that local door, and only a caller
    that explicitly names "prod" (dispatch_deployment_stage_approval's
    serving_authority route) should ever reach this sibling.
    """
    client = plane["client"]
    token = plane["owner_headers"]["Authorization"].split(" ", 1)[1]
    connection = HttpsConnection(
        api_url="https://serving-build.example", token=token, env="prod"
    )
    relayed: list[str] = []

    def open_no_redirect(request, timeout=None):
        del timeout
        payload = json.loads(request.data.decode("utf-8"))
        relayed.append(str(payload["function"]))
        response = client.post(
            "/v1/functions/call",
            headers={
                "Authorization": request.get_header("Authorization"),
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code >= 400:
            raise urllib.error.HTTPError(
                request.full_url,
                response.status_code,
                response.reason_phrase,
                dict(response.headers),
                io.BytesIO(response.content),
            )
        return _RelayResponse(response.content, dict(response.headers))

    def resolve_https_connection(*, explicit_env=None):
        return connection if explicit_env == "prod" else None

    monkeypatch.setattr(https_transport, "open_no_redirect", open_no_redirect)
    monkeypatch.setattr(
        https_transport, "resolve_https_connection", resolve_https_connection
    )
    monkeypatch.setattr(https_transport, "record_outcome", lambda *_a, **_k: None)
    return relayed


def _hide_from_the_https_sibling_only(monkeypatch, function_ids: set[str]) -> None:
    """Simulate an old serving build missing ``function_ids``.

    Must hide them only from requests that cross the http boundary — the
    admin driver's own local in-process dispatch is the SAME Python
    process and must stay unaffected, or this would prove nothing about
    which transport each function actually used.
    """
    from yoke_core.api.routes import functions as functions_route

    real_dispatch = functions_route.dispatch

    def dispatch_on_an_old_serving_build(request, ambient_session_id=""):
        function_id = (
            request.get("function") if isinstance(request, dict) else request.function
        )
        if function_id in function_ids:
            return FunctionCallResponse(
                success=False,
                function=str(function_id),
                version="v1",
                error=FunctionError(
                    code="function_not_registered",
                    message=f"function id {function_id!r} is not registered",
                ),
            )
        return real_dispatch(request, ambient_session_id=ambient_session_id)

    monkeypatch.setattr(functions_route, "dispatch", dispatch_on_an_old_serving_build)


def test_admin_candidate_keeps_local_scoped_qa_while_its_https_sibling_still_relays_approval(
    serving_plane,  # noqa: F811 - fixture re-export, this is the intended shadow
    monkeypatch,
) -> None:
    conn = serving_plane["conn"]
    plan_id = create_smoke_plan(conn, project=PROJECT, slug="mixed-build-smoke")
    stages = [dict(stage) for stage in _STAGES]
    stages[3]["cases"] = {"plan_id": plan_id, "case_keys": ["command-smoke"]}
    _replace_flow(conn, stages)
    conn.execute(
        "UPDATE deployment_flows SET definition_schema_version=2 WHERE id=%s", (FLOW,)
    )
    conn.commit()
    seed_frozen_scoped_qa_run(
        conn,
        run_id=RUN_ID,
        project=PROJECT,
        flow=FLOW,
        stages=stages,
        item_id=ITEM_ID,
        lineage=LINEAGE,
    )

    _admin_driver_env(monkeypatch, serving_plane)
    monkeypatch.setattr(deploy_pipeline, "resolve_project_checkout_path", lambda _p: "")

    # The candidate's ambient connection is the admin door (no explicit env
    # named), so an unqualified call_dispatcher picks it up automatically.
    # dispatch_deployment_stage_approval always names "prod" explicitly, so
    # it alone reaches the https sibling below regardless of the ambient
    # connection — exactly what serving_authority is for.
    relayed = _install_named_serving_sibling(monkeypatch, serving_plane)

    from yoke_cli.config import machine_config

    monkeypatch.setattr(machine_config, "active_env", lambda *a, **k: "prod-db-admin")
    monkeypatch.setattr(
        machine_config,
        "load_config",
        lambda *a, **k: {
            "connections": {
                "prod": {"transport": "https"},
                "prod-db-admin": {"transport": "local-postgres"},
            }
        },
    )
    _hide_from_the_https_sibling_only(
        monkeypatch,
        {DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION, RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION},
    )

    original_dispatch = deploy_pipeline._dispatch_step_runner

    def dispatch_stage(stage, **kwargs):
        if stage["name"] == "deploy":
            receipt = allocate_deployment_stage_receipt(
                conn,
                run_id=RUN_ID,
                stage_name="deploy",
                correlation_id=f"{RUN_ID}-deploy-1",
                target_kind="run_preview",
                executor="test",
                commit=False,
            )
            complete_deployment_stage_receipt(
                conn,
                receipt_id=int(receipt["id"]),
                correlation_id=str(receipt["correlation_id"]),
                status="ready",
                target_name="candidate-preview",
                observed_url="https://candidate-preview.example.test",
                observed_release_lineage=LINEAGE,
                executor_receipt="test://deploy-ready",
                commit=True,
            )
        return original_dispatch(stage, **kwargs)

    monkeypatch.setattr(deploy_pipeline, "_dispatch_step_runner", dispatch_stage)

    assert (
        deploy_pipeline.run_pipeline(RUN_ID) == deploy_pipeline.EXIT_AWAITING_APPROVAL
    )
    _invoke(
        "decision_requests.resolve",
        {"request_id": _decision_request_id(conn, RUN_ID), "action": "approve"},
    )

    # Resuming past approval reaches the new scoped-QA stage; nothing has
    # been materialized yet, so this must pause as EXIT_AWAITING_QA — never
    # a false success and never a hard stage failure.
    assert deploy_pipeline.run_pipeline(RUN_ID) == deploy_pipeline.EXIT_AWAITING_QA
    unresolved = conn.execute(
        "SELECT status,current_stage FROM deployment_runs WHERE id=%s",
        (RUN_ID,),
    ).fetchone()
    assert tuple(unresolved) != ("succeeded", "complete")

    # The pre-existing approval evaluation relayed to the https sibling,
    # unchanged. The two new scoped-QA operations never did — proving they
    # took the local registered route on this admin-connected candidate,
    # not the same https connection that would have refused them.
    assert "deployment_runs.stage_approval.evaluate" in relayed
    assert DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION not in relayed
    assert RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION not in relayed
