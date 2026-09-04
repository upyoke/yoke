"""Rollout compatibility for resident read-only observation batching."""

import json
import urllib.request

from yoke_cli.transport.bounded_json_http import request_json
from yoke_contracts.hook_evaluator_protocol import (
    HOOK_OBSERVATION_BATCH_CAPABILITY,
)
from yoke_core.api.routes.hooks import HookEvaluateResponse
from yoke_harness.hook_resident_http import ResidentHttpOpener
from yoke_harness.hook_resident_observations import DeferredObservationOpener


def test_server_response_advertises_observation_batch_capability() -> None:
    response = HookEvaluateResponse(
        stdout="",
        exit_code=0,
        wait_ms=0,
        degraded=[],
        outcome="completed",
    ).model_dump(mode="json")
    assert response["capabilities"] == [HOOK_OBSERVATION_BATCH_CAPABILITY]


def test_resident_enables_batching_only_after_server_advertisement() -> None:
    opener = ResidentHttpOpener()
    try:
        assert not opener.observation_batch_supported()
        opener._record_capabilities(json.dumps({"outcome": "completed"}).encode())
        assert not opener.observation_batch_supported()
        opener._record_capabilities(
            json.dumps(
                {
                    "capabilities": [HOOK_OBSERVATION_BATCH_CAPABILITY],
                }
            ).encode()
        )
        assert opener.observation_batch_supported()
    finally:
        opener.close()


def test_deferred_observation_preserves_transport_final_url() -> None:
    opener = DeferredObservationOpener()
    request = urllib.request.Request(
        "https://example.test/v1/hooks/evaluate",
        data=json.dumps({"execution_provenance": {}}).encode(),
        method="POST",
        headers={"Authorization": "Bearer test"},
    )
    response = request_json(
        request,
        timeout_seconds=1,
        replay_safe=False,
        opener=opener,
    )
    assert response.payload["outcome"] == "completed"
    assert opener.observation(hook_wait_ms=1).endpoint == (
        "https://example.test/v1/hooks/telemetry/batch"
    )
