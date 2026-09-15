"""Deployment drivers preserve gates against a local admin connection.

Split out of test_deploy_pipeline_https_execution.py so that module stays
under the authored-file line budget; this file owns the "candidate driver
talking to the local *-db-admin connection" half of that coverage, reusing
its shared fixtures and helpers.
"""

from __future__ import annotations

import io
import urllib.error

from runtime.api.domain.test_deploy_pipeline_https_execution import (
    FLOW,
    LINEAGE,
    PROJECT,
    _decision_request_id,
    _invoke,
    _RelayResponse,
    _replace_flow,
    serving_plane,  # noqa: F401 - pytest fixture re-export
)
from yoke_cli.commands.adapters.deployment_execution_authority import (
    execution_connection_error,
)
from yoke_cli.transport import dispatcher as client_dispatcher
from yoke_cli.transport import https as https_transport
from yoke_cli.transport.https import HttpsConnection
from yoke_core.domain import deploy_pipeline, deploy_pipeline_control_plane


def _admin_driver_env(monkeypatch, plane) -> None:
    """The candidate driver's own ambient identity: an admin door, no https."""
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    monkeypatch.setenv("YOKE_ACTOR_ID", str(plane["owner_id"]))
    monkeypatch.setattr(
        client_dispatcher, "_resolve_session_id", lambda: plane["owner_session"]
    )
    monkeypatch.setattr(deploy_pipeline, "resolve_project_checkout_path", lambda _p: "")


def _bootstrap_admin_env(monkeypatch, plane) -> None:
    """The admin driver with no https plane reachable at all — not even named."""
    _admin_driver_env(monkeypatch, plane)
    monkeypatch.setattr(
        https_transport, "resolve_https_connection", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        https_transport,
        "relay_https",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local admin bootstrap contacted the serving API")
        ),
    )


def test_admin_candidate_relays_approval_and_resume_to_the_serving_plane(
    serving_plane,  # noqa: F811 - fixture re-export, this is the intended shadow
    monkeypatch,
) -> None:
    """A mixed-build admin driver relays approval and scoped-QA resume.

    The release driver holds a direct admin door into the database (it is
    deploying a candidate build), while the deployed build's own API is
    the named https sibling that must evaluate the approval verdict and
    the resume's scoped-QA facts — mirroring the self-deploy scenario
    dispatch_deployment_stage_approval already relies on. Both the
    pre-existing approval dispatch and the new resume gate route through
    that same named plane rather than either failing or evaluating
    against the candidate's own code.
    """
    conn = serving_plane["conn"]
    _replace_flow(
        conn,
        [
            {"name": "preflight", "step_runner": "auto", "qa_kind": "preflight"},
            {
                "name": "approve-deploy",
                "step_runner": "human-approval",
                "qa_kind": "approval",
                "approvals": {"roles": ["owner"], "actors": []},
            },
            {"name": "complete", "step_runner": "auto"},
        ],
    )
    _admin_driver_env(monkeypatch, serving_plane)

    client = serving_plane["client"]
    token = serving_plane["owner_headers"]["Authorization"].split(" ", 1)[1]
    serving_connection = HttpsConnection(
        api_url="https://serving-build.example", token=token, env="prod"
    )
    relayed: list[str] = []

    def open_no_redirect(request, timeout=None):
        del timeout
        import json as _json

        payload = _json.loads(request.data.decode("utf-8"))
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
        # The admin driver's own ambient connection is not an https plane
        # at all (matching _bootstrap_admin_env); only an explicitly named
        # lookup for the serving build's own env resolves to anything.
        return serving_connection if explicit_env == "prod" else None

    from yoke_cli.config import machine_config

    monkeypatch.setattr(https_transport, "open_no_redirect", open_no_redirect)
    monkeypatch.setattr(
        https_transport, "resolve_https_connection", resolve_https_connection
    )
    monkeypatch.setattr(https_transport, "record_outcome", lambda *_a, **_k: None)
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

    run_id = str(
        _invoke(
            "deployment_runs.create",
            {"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
        )["run_id"]
    )
    assert execution_connection_error(run_id) is None
    # First pass pauses at the approval stage and persists current_stage,
    # so the second call below is a genuine resume, not a fresh run.
    assert (
        deploy_pipeline.run_pipeline(run_id) == deploy_pipeline.EXIT_AWAITING_APPROVAL
    )
    _invoke(
        "decision_requests.resolve",
        {"request_id": _decision_request_id(conn, run_id), "action": "approve"},
    )
    assert deploy_pipeline.run_pipeline(run_id) == deploy_pipeline.EXIT_SUCCESS
    succeeded = conn.execute(
        "SELECT status,current_stage FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    assert tuple(succeeded) == ("succeeded", "complete")
    assert "deployment_runs.stage_approval.evaluate" in relayed
    # The resume gate evaluates on every resume, scoped-QA or not — this
    # flow has no scoped-QA stage, so the relayed message is empty, but
    # the relay itself (not a local connect()) is what mixed-build safety
    # depends on.
    assert "deployment_runs.qa_stage.resume_refusals" in relayed


def test_local_admin_candidate_bootstraps_execution_handlers(
    serving_plane,  # noqa: F811 - fixture re-export, this is the intended shadow
    monkeypatch,
) -> None:
    conn = serving_plane["conn"]
    _replace_flow(
        conn,
        [
            {"name": "bootstrap", "step_runner": "auto", "qa_kind": "bootstrap"},
            {"name": "complete", "step_runner": "auto"},
        ],
    )
    _bootstrap_admin_env(monkeypatch, serving_plane)

    called: list[str] = []
    original_call = deploy_pipeline_control_plane._call

    def record_call(function_id: str, run_id: str, payload: dict):
        called.append(function_id)
        return original_call(function_id, run_id, payload)

    monkeypatch.setattr(deploy_pipeline_control_plane, "_call", record_call)
    run_id = str(
        _invoke(
            "deployment_runs.create",
            {"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
        )["run_id"]
    )
    assert execution_connection_error(run_id) is None
    assert deploy_pipeline.run_pipeline(run_id) == deploy_pipeline.EXIT_SUCCESS
    assert {
        "deployment_runs.execution.context",
        "deployment_runs.execution.update",
        "deployment_runs.execution.qa_seed",
        "deployment_runs.execution.qa_record",
        "deployment_runs.execution.qa_pending",
    }.issubset(called)
