# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

import urllib.error

from runtime.api.domain import (
    deployment_execution_serving_authority_test_support as serving_fixture,
)

from yoke_cli.transport import dispatcher as client_dispatcher

from yoke_cli.transport import https as https_transport

from yoke_cli.transport.https import HttpsConnection

from yoke_contracts.api.function_call import TargetRef

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

from yoke_core.domain import (
    control_plane_transport,
    deploy_pipeline,
    deploy_pipeline_failure,
)

serving_plane = serving_fixture.serving_plane

PROJECT = serving_fixture.PROJECT

FLOW = serving_fixture.FLOW

LINEAGE = serving_fixture.LINEAGE


class _RelayResponse(io.BytesIO):
    def __init__(self, body: bytes, headers) -> None:
        super().__init__(body)
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def _invoke(function_id: str, payload: dict, *, run_id: str = "") -> dict:
    target = (
        TargetRef(kind="workflow_run", workflow_run_id=run_id)
        if run_id
        else TargetRef(kind="global")
    )
    response = call_dispatcher(
        function_id=function_id,
        target=target,
        payload=payload,
    )
    assert response.success is True, response.error
    return dict(response.result or {})


def _replace_flow(conn, stages: list[dict]) -> None:
    # An item-scoped QA stage proves members against snapshots only a
    # custody flow freezes, so composition refuses one without custody.
    custody = any(stage.get("scope") == "item" for stage in stages)
    conn.execute(
        "UPDATE deployment_flows SET stages=%s,takes_delivery_custody=%s,definition_schema_version=2 WHERE id=%s",
        (json.dumps(stages), int(custody), FLOW),
    )
    conn.commit()


def _install_test_https(monkeypatch, plane) -> list[str]:
    client = plane["client"]
    session_id = plane["owner_session"]
    token = plane["owner_headers"]["Authorization"].split(" ", 1)[1]
    connection = HttpsConnection(
        api_url="https://external-control.example",
        token=token,
        env="external-https",
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

    def local_dispatch_refused(*_args, **_kwargs):
        raise AssertionError("HTTPS deployment driver used local DB dispatch")

    monkeypatch.setattr(https_transport, "open_no_redirect", open_no_redirect)
    monkeypatch.setattr(
        https_transport,
        "resolve_https_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(https_transport, "record_outcome", lambda *_a, **_k: None)
    monkeypatch.setattr(client_dispatcher, "_call_local", local_dispatch_refused)
    monkeypatch.setattr(client_dispatcher, "_resolve_session_id", lambda: session_id)
    monkeypatch.setattr(
        control_plane_transport,
        "serving_control_plane_env",
        lambda: connection.env,
    )
    return relayed


def _decision_request_id(conn, run_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM decision_requests WHERE subject_type='deployment_stage' "
        "AND subject_key=%s AND status='pending' ORDER BY id DESC LIMIT 1",
        (f"{run_id}:approve-deploy",),
    ).fetchone()
    assert row is not None
    return int(row[0])
