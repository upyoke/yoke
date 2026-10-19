"""Dispatch-path tests for the identity admin yoke CLI wrappers."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"ok": True},
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run_capture(*argv: str) -> tuple[int, str, str]:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_ok,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                out = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = cli_main(list(argv))
                return rc, out.getvalue(), err.getvalue()


def test_registry_maps_identity_tokens_to_function_ids() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    for action in ("create", "list", "revoke"):
        assert ("identity", "invite", action) not in SUBCOMMAND_REGISTRY
    assert SUBCOMMAND_REGISTRY[("identity", "link", "set")][0] == ("identity.link.set")


@pytest.mark.parametrize("action", ["create", "list", "revoke"])
def test_retired_invite_spelling_refuses_without_dispatch(action) -> None:
    rc, _out, _err = _run_capture("identity", "invite", action)
    assert rc == 2
    assert _CAPTURED_REQUESTS == []


def test_link_set_identity_shape_dispatches() -> None:
    rc, _out, _err = _run_capture(
        "identity",
        "link",
        "set",
        "--actor",
        "3",
        "--issuer",
        "https://issuer.example",
        "--subject",
        "sub-1",
        "--email",
        "dev@example.com",
    )
    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "identity.link.set"
    assert req.payload == {
        "actor": "3",
        "issuer": "https://issuer.example",
        "subject": "sub-1",
        "email": "dev@example.com",
    }
