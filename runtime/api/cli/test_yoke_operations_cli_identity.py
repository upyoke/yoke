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

    assert SUBCOMMAND_REGISTRY[("identity", "invite", "create")][0] == (
        "identity.invite.create"
    )
    assert SUBCOMMAND_REGISTRY[("identity", "invite", "list")][0] == (
        "identity.invite.list"
    )
    assert SUBCOMMAND_REGISTRY[("identity", "invite", "revoke")][0] == (
        "identity.invite.revoke"
    )
    assert SUBCOMMAND_REGISTRY[("identity", "link", "set")][0] == (
        "identity.link.set"
    )
    assert SUBCOMMAND_REGISTRY[("identity", "autojoin", "set")][0] == (
        "identity.autojoin.set"
    )


def test_invite_create_dispatches_email_role_actor_org() -> None:
    rc, _out, _err = _run_capture(
        "identity", "invite", "create", "dev@example.com",
        "--role", "viewer", "--actor", "casey", "--org", "default",
    )
    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "identity.invite.create"
    assert req.target.kind == "global"
    assert req.payload == {
        "email": "dev@example.com",
        "role": "viewer",
        "actor": "casey",
        "org": "default",
    }


def test_invite_list_and_revoke_dispatch() -> None:
    rc, _out, _err = _run_capture(
        "identity", "invite", "list", "--status", "pending",
    )
    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {"status": "pending"}

    rc, _out, _err = _run_capture("identity", "invite", "revoke", "7")
    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {"invite_id": 7}


def test_link_set_identity_shape_dispatches() -> None:
    rc, _out, _err = _run_capture(
        "identity", "link", "set", "--actor", "3",
        "--issuer", "https://issuer.example", "--subject", "sub-1",
        "--email", "dev@example.com",
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


def test_autojoin_set_domain_and_clear_are_exclusive() -> None:
    rc, _out, _err = _run_capture(
        "identity", "autojoin", "set", "example.com",
    )
    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {"domain": "example.com"}

    rc, _out, _err = _run_capture("identity", "autojoin", "set", "--clear")
    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {"domain": None}

    rc, _out, _err = _run_capture("identity", "autojoin", "set")
    assert rc == 2
    rc, _out, _err = _run_capture(
        "identity", "autojoin", "set", "example.com", "--clear",
    )
    assert rc == 2
