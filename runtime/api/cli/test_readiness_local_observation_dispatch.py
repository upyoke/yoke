"""`yoke readiness ...` answers a request to read this machine's checkout.

The adapter dispatches once. When the answer says the file-reading checks
went unperformed and publishes what they needed, the adapter runs them
against this machine's checkout and re-dispatches the same call carrying
what they found. The verdict is still the control plane's — nothing is
judged here.
"""

from __future__ import annotations

from io import StringIO
from contextlib import redirect_stdout
from unittest.mock import patch

from yoke_cli.commands.adapters.readiness import (
    readiness_check,
    readiness_repair_stale_count,
)
from yoke_contracts.api.function_call import FunctionCallResponse

_REQUEST = {
    "item_id": 1800,
    "item_ref": "YOK-1800",
    "project_id": 7,
    "spec_sha256": "abc",
    "spec_text": "spec",
    "checks": ["verify_function_owners"],
}
_OBSERVATIONS = {"spec_sha256": "abc", "checks": ["verify_function_owners"]}


def _response(result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="readiness.check.run",
        version="v1",
        request_id="r1",
        result=result,
    )


def _run(adapter, args, responses, observations):
    """Run one adapter over a scripted dispatch sequence."""
    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return responses[len(calls) - 1]

    with (
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        patch("yoke_cli.commands._helpers.call_dispatcher", side_effect=_dispatch),
        patch(
            "yoke_cli.commands.adapters.readiness.call_dispatcher",
            side_effect=_dispatch,
        ),
        patch(
            "yoke_cli.commands.adapters.readiness_local_compose.collect_observations",
            return_value=observations,
        ),
        redirect_stdout(StringIO()),
    ):
        adapter(args)
    return calls


def test_observations_are_collected_and_the_same_call_re_dispatched() -> None:
    unavailable = _response({
        "verdict": "unavailable",
        "local_execution_request": _REQUEST,
    })
    resolved = _response({"verdict": "pass"})

    calls = _run(
        readiness_check, ["YOK-1800"], [unavailable, resolved], _OBSERVATIONS,
    )

    assert len(calls) == 2
    assert calls[1]["function_id"] == "readiness.check.run"
    assert calls[1]["payload"]["local_observations"] == _OBSERVATIONS


def test_a_machine_without_the_checkout_leaves_the_first_answer_standing() -> None:
    """No observations to send, so the unperformed verdict is the answer."""
    unavailable = _response({
        "verdict": "unavailable",
        "local_execution_request": _REQUEST,
    })

    calls = _run(readiness_check, ["YOK-1800"], [unavailable], None)

    assert len(calls) == 1


def test_a_host_that_ran_the_checks_is_not_asked_again() -> None:
    """No request published means nothing was left unperformed."""
    calls = _run(
        readiness_check, ["YOK-1800"], [_response({"verdict": "pass"})], _OBSERVATIONS,
    )

    assert len(calls) == 1


def test_the_repairs_take_the_same_route() -> None:
    """Repair rewrites from disk, so it needs the same observations."""
    refused = _response({
        "success": False,
        "rerun_verdict": "unavailable",
        "local_execution_request": _REQUEST,
    })
    repaired = _response({"success": True, "rerun_verdict": "pass"})

    calls = _run(
        readiness_repair_stale_count,
        ["--item", "YOK-1800"],
        [refused, repaired],
        _OBSERVATIONS,
    )

    assert len(calls) == 2
    assert calls[1]["function_id"] == "readiness.repair_stale_count"
    assert calls[1]["payload"]["local_observations"] == _OBSERVATIONS


def test_the_client_survives_an_install_without_the_engine() -> None:
    """A thin client cannot observe; it must not fail trying."""
    from yoke_cli.commands.adapters import readiness_local_compose

    with patch(
        "importlib.import_module", side_effect=ImportError("no yoke_core")
    ):
        assert readiness_local_compose.collect_observations(_REQUEST) is None
