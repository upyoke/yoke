"""Dispatch coverage for organization identity and settings commands."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

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


def _run(*args: str) -> int:
    _CAPTURED.clear()
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_ok,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return cli_main(list(args))


def test_registry_maps_organization_commands() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("organizations", "get")][0] == ("organizations.get")
    assert SUBCOMMAND_REGISTRY[("organizations", "settings", "get")][0] == (
        "organizations.settings.get"
    )
    assert SUBCOMMAND_REGISTRY[("organizations", "settings", "merge")][0] == (
        "organizations.settings.merge"
    )
    assert SUBCOMMAND_REGISTRY[("organizations", "domain", "set")][0] == (
        "organizations.domain.set"
    )


def test_settings_get_and_merge_dispatch_scalar_paths() -> None:
    assert (
        _run(
            "organizations",
            "settings",
            "get",
            "--path",
            "messages.delivery_lease_seconds",
            "--org",
            "default",
        )
        == 0
    )
    request = _CAPTURED[-1]
    assert request.function == "organizations.settings.get"
    assert request.payload == {
        "path": "messages.delivery_lease_seconds",
        "org": "default",
    }

    assert (
        _run(
            "organizations",
            "settings",
            "merge",
            "--set",
            "messages.delivery_lease_seconds=45",
            "--set",
            "membership.auto_join_domain_verified=true",
        )
        == 0
    )
    request = _CAPTURED[-1]
    assert request.function == "organizations.settings.merge"
    assert request.payload == {
        "assignments": {
            "messages.delivery_lease_seconds": 45,
            "membership.auto_join_domain_verified": True,
        },
    }


def test_domain_set_and_clear_are_exclusive() -> None:
    assert _run("organizations", "domain", "set", "example.com") == 0
    assert _CAPTURED[-1].function == "organizations.domain.set"
    assert _CAPTURED[-1].payload == {"domain": "example.com"}

    assert _run("organizations", "domain", "set", "--clear") == 0
    assert _CAPTURED[-1].payload == {"domain": None}

    assert _run("organizations", "domain", "set") == 2
    assert (
        _run(
            "organizations",
            "domain",
            "set",
            "example.com",
            "--clear",
        )
        == 2
    )
