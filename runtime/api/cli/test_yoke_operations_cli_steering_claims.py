"""CLI and inventory contracts for project steering work claims."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallRequest, FunctionCallResponse
from yoke_core.domain.strategy_docs_defaults import NEAR_TERM_PLAN_SLUG


_CAPTURED: list[FunctionCallRequest] = []


def _claim(
    claim_id: int,
    *,
    holder: str = "steering-session",
    released_at: str | None = None,
) -> dict:
    return {
        "id": claim_id,
        "session_id": holder,
        "target_kind": "steering",
        "scope": {"project_id": 7},
        "claim_type": "exclusive",
        "claimed_at": "2026-08-25T17:00:00Z",
        "last_heartbeat": "2026-08-25T17:01:00Z",
        "released_at": released_at,
        "release_reason": "completed" if released_at else None,
        "document_claim": {
            "strategy_doc_slug": NEAR_TERM_PLAN_SLUG,
            "slug": NEAR_TERM_PLAN_SLUG,
        },
        "holder_actor_label": "ben",
        "holder_machine": "studio",
    }


def _stub_response(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED.append(request)
    if request.function == "claims.steering.list":
        result = {
            "claims": [
                _claim(41),
                _claim(42, holder="other-session"),
            ]
        }
    else:
        claim = _claim(41)
        claim["message_handoff"] = {
            "drained_count": 0,
            "parked_count": 0,
            "digest": "",
        }
        result = {"claim": claim}
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result=result,
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED.clear()


def _run(*argv: str):
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "steering-session"}):
        with (
            patch(
                "yoke_core.domain.yoke_function_dispatch.dispatch",
                side_effect=_stub_response,
            ),
            patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = cli_main(list(argv))
            return rc, stdout.getvalue(), stderr.getvalue()


def test_acquire_dispatches_project_target_and_reason() -> None:
    rc, _out, err = _run(
        "claims",
        "steering",
        "acquire",
        "--project",
        "alpha",
        "--doc",
        "AREA-PLAN",
        "--reason",
        "guide planning",
    )
    assert rc == 0, err
    request = _CAPTURED[-1]
    assert request.function == "claims.steering.acquire"
    assert request.target.kind == "global"
    assert request.target.project_id == "alpha"
    assert request.payload == {
        "document": "AREA-PLAN",
        "reason": "guide planning",
    }


def test_acquire_without_doc_takes_the_whole_project_seat() -> None:
    rc, out, err = _run(
        "claims",
        "steering",
        "acquire",
        "--project",
        "alpha",
    )
    assert rc == 0, err
    assert _CAPTURED[-1].payload == {}
    assert "scope=7 (whole project)" in out
    assert "holder=steering-session" in out
    assert "inherited 0 steering message(s)" in out


def test_release_dispatches_claim_target_and_reason() -> None:
    rc, out, err = _run(
        "claims",
        "steering",
        "release",
        "41",
        "--reason",
        "steering complete",
    )
    assert rc == 0, err
    request = _CAPTURED[-1]
    assert request.function == "claims.steering.release"
    assert request.target.kind == "claim"
    assert request.target.claim_id == 41
    assert request.payload == {"reason": "steering complete"}
    assert "released steering claim 41" in out


def test_release_rejects_non_integer_claim_id() -> None:
    rc, _out, err = _run(
        "claims",
        "steering",
        "release",
        "nope",
        "--reason",
        "done",
    )
    assert rc == 2
    assert "CLAIM_ID must be an integer" in err
    assert _CAPTURED == []


def test_list_dispatches_project_and_filters() -> None:
    rc, _out, err = _run(
        "claims",
        "steering",
        "list",
        "--project",
        "alpha",
        "--session-id",
        "other-session",
        "--active-only",
    )
    assert rc == 0, err
    request = _CAPTURED[-1]
    assert request.function == "claims.steering.list"
    assert request.target.kind == "global"
    assert request.target.project_id == "alpha"
    assert request.payload == {
        "session_id": "other-session",
        "active_only": True,
    }


def test_human_list_names_scope_holder_and_machine() -> None:
    rc, out, err = _run("claims", "steering", "list", "--project", "alpha")
    assert rc == 0, err
    assert "claim_id\tscope\tholder\tmachine\tsession\tstate" in out
    assert "41\t7 (whole project)\tben\tstudio\tsteering-session\tactive" in out
    assert "42\t7 (whole project)\tben\tstudio\tother-session\tactive" in out


def test_json_list_emits_response_envelope() -> None:
    rc, out, err = _run(
        "claims",
        "steering",
        "list",
        "--project",
        "alpha",
        "--json",
    )
    assert rc == 0, err
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["function"] == "claims.steering.list"
    assert payload["result"]["claims"][0]["scope"] == {"project_id": 7}


@pytest.mark.parametrize("operation", ("acquire", "release", "list"))
def test_help_exposes_steering_grammar(operation: str) -> None:
    with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cli_main(["claims", "steering", operation, "--help"])
    assert rc == 0
    assert f"yoke claims steering {operation}" in stdout.getvalue()


def test_registry_inventory_and_usage_expose_all_operations() -> None:
    from yoke_cli.commands.adapters.usage import ADAPTER_USAGE
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_core.api.service_client_structured_api_adapter_inventory import (
        adapter_index,
    )

    expected = {
        "acquire": "claims.steering.acquire",
        "release": "claims.steering.release",
        "list": "claims.steering.list",
    }
    inventory = adapter_index()
    for operation, function_id in expected.items():
        assert SUBCOMMAND_REGISTRY[("claims", "steering", operation)][0] == function_id
        assert function_id in ADAPTER_USAGE
        assert function_id in inventory


def test_function_registry_exposes_steering_contracts() -> None:
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_registry import lookup

    register_all_handlers()
    acquire = lookup("claims.steering.acquire")
    release = lookup("claims.steering.release")
    listed = lookup("claims.steering.list")
    assert acquire is not None and acquire.claim_required_kind is None
    assert acquire.target_kinds == ("global",)
    assert acquire.emitted_event_names == ("SteeringClaimed",)
    assert "strategy_doc_claims_insert_or_pair" in acquire.side_effects
    assert release is not None and release.claim_required_kind == "self_only"
    assert release.target_kinds == ("claim",)
    assert "paired_strategy_doc_claim_update_released_at" in release.side_effects
    assert listed is not None and listed.side_effects == ()
