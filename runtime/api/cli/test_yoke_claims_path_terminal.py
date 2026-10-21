"""The public CLI dispatches terminal claim mutations without internal clients."""

import pytest

from runtime.api.cli.test_yoke_operations_cli_claims import _CAPTURED, _run


@pytest.fixture(autouse=True)
def clean_capture():
    _CAPTURED.clear()
    yield
    _CAPTURED.clear()


@pytest.mark.parametrize("action", ["release", "cancel"])
def test_terminal_dispatch(action):
    code, _, _ = _run(
        "claims",
        "path",
        action,
        "--item",
        "EXT-42",
        "--claim-id",
        "17",
        "--reason",
        "coverage finished",
        "--json",
    )
    assert code == 0
    request = _CAPTURED[-1]
    assert request.function == f"claims.path.{action}"
    assert request.target.public_ref == "EXT-42"
    assert request.payload == {"claim_id": 17, "reason": "coverage finished"}


@pytest.mark.parametrize("action", ["release", "cancel"])
def test_reason_and_item_required(action):
    code, _, _ = _run("claims", "path", action, "--claim-id", "17")
    assert code == 2


@pytest.mark.parametrize("action", ["release", "cancel"])
def test_invalid_claim_id_names_recovery(action):
    code, _, error = _run(
        "claims",
        "path",
        action,
        "--item",
        "EXT-42",
        "--claim-id",
        "not-an-integer",
        "--reason",
        "finished",
    )
    assert code == 2
    assert "--claim-id must be an integer" in error
