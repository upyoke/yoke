"""CLI coverage for readiness and path-claim gate wrappers."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


_CAPTURED: list[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"ok": True},
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED.clear()


def _run(*argv: str) -> tuple[int, str, str]:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_ok,
        ), patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = cli_main(list(argv))
            return rc, out.getvalue(), err.getvalue()


def test_readiness_check_dispatches_item_target() -> None:
    rc, _out, err = _run(
        "readiness", "check", "YOK-1800", "--skip-readiness-check",
    )
    assert rc == 0, err
    req = _CAPTURED[-1]
    assert req.function == "readiness.check.run"
    assert req.target.kind == "item"
    assert req.target.item_ref == "YOK-1800"
    assert req.payload == {"skip_readiness_check": True}


def test_readiness_prd_validate_dispatches_item_target() -> None:
    rc, _out, err = _run(
        "readiness", "prd-validate", "YOK-1800", "--strict",
    )
    assert rc == 0, err
    req = _CAPTURED[-1]
    assert req.function == "readiness.prd_validate.run"
    assert req.target.kind == "item"
    assert req.target.item_ref == "YOK-1800"
    assert req.payload == {"strict": True}


def test_readiness_repair_commands_dispatch() -> None:
    rc, _out, err = _run(
        "readiness", "repair-stale-count", "--item", "1800",
    )
    assert rc == 0, err
    assert _CAPTURED[-1].function == "readiness.repair_stale_count"
    assert _CAPTURED[-1].target.item_ref == "1800"

    rc, _out, err = _run(
        "readiness", "repair-claim-coverage", "--item", "YOK-1800",
    )
    assert rc == 0, err
    assert _CAPTURED[-1].function == "readiness.repair_claim_coverage"
    assert _CAPTURED[-1].target.item_ref == "YOK-1800"


def test_claims_path_gate_and_activation_dispatch() -> None:
    rc, _out, err = _run("claims", "path", "required-gate", "YOK-1800")
    assert rc == 0, err
    req = _CAPTURED[-1]
    assert req.function == "claims.path.required_gate"
    assert req.target.item_ref == "YOK-1800"
    assert req.payload == {}

    with patch(
        "yoke_cli.commands.adapters.claims_path_flow"
        ".sync_local_snapshot_for_write"
    ) as sync:
        rc, _out, err = _run(
            "claims", "path", "activation-run", "--item", "1800",
        )
    assert rc == 0, err
    sync.assert_called_once_with(
        project=None, integration_target=None, session_id=None,
    )
    req = _CAPTURED[-1]
    assert req.function == "claims.path.activation_run"
    assert req.target.item_ref == "1800"
    assert req.payload == {}
