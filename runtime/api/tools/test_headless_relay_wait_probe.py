"""A worker's message alone cannot establish elapsed release proof."""

import json

from runtime.api.tools.headless_relay_wait_probe import WAIT_SECONDS, completion_matches


def test_completion_requires_both_elapsed_clocks_and_launch_environment():
    proof = {
        "nonce": "probe",
        "launch_timeout_ms": "3600000",
        "elapsed_seconds": WAIT_SECONDS,
    }
    assert completion_matches(json.dumps(proof), "probe", WAIT_SECONDS)
    assert not completion_matches(json.dumps(proof), "other", WAIT_SECONDS)
    assert not completion_matches(json.dumps(proof), "probe", 600)
    proof["elapsed_seconds"] = 600
    assert not completion_matches(json.dumps(proof), "probe", WAIT_SECONDS)
    proof["elapsed_seconds"] = WAIT_SECONDS
    proof["launch_timeout_ms"] = "600000"
    assert not completion_matches(json.dumps(proof), "probe", WAIT_SECONDS)


def test_completion_rejects_diagnostics_and_nonobjects():
    for body in ("stopped after reaching its background time limit", "null", "[]"):
        assert not completion_matches(body, "probe", WAIT_SECONDS)
