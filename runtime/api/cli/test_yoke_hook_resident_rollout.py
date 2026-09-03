"""Rollout compatibility for resident read-only observation batching."""

import json

from yoke_contracts.hook_evaluator_protocol import (
    HOOK_OBSERVATION_BATCH_CAPABILITY,
)
from yoke_core.api.routes.hooks import HookEvaluateResponse
from yoke_harness.hook_resident_http import ResidentHttpOpener


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
