"""Tests for the human-only coordination-lease recovery command."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from yoke_cli.commands import coordination_lease as subject
from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallResponse


def test_https_connection_is_refused_before_runtime_import(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(subject, "remote_without_admin_authority", lambda: True)
    monkeypatch.setattr(
        subject.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(AssertionError("must not import")),
    )

    assert subject.coordination_lease_release([]) == 1
    assert "not relayed over HTTPS" in capsys.readouterr().err


def test_local_authority_delegates_to_audited_operator_surface(monkeypatch) -> None:
    monkeypatch.setattr(subject, "remote_without_admin_authority", lambda: False)
    calls: list[list[str]] = []
    module = SimpleNamespace(
        cmd_coordination_lease_release=lambda args: calls.append(args) or 0,
    )
    monkeypatch.setattr(subject.importlib, "import_module", lambda _name: module)
    args = [
        "--project",
        "yoke",
        "--key",
        "LIVE_DB_MIGRATION:primary",
        "--reason",
        "stale holder confirmed",
    ]

    assert subject.coordination_lease_release(args) == 0
    assert calls == [args]


def test_aggregate_tool_registry_routes_public_command() -> None:
    from yoke_cli.commands.tool_shaped import resolve_tool_shaped

    resolved = resolve_tool_shaped(
        ["coordination-lease", "release", "--project", "yoke"]
    )
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is subject.coordination_lease_release
    assert remaining == ["--project", "yoke"]


def test_function_call_list_wins_over_tool_shaped_group() -> None:
    from yoke_cli.commands.adapters.claims_coordination_lease import (
        claims_coordination_lease_list,
    )
    from yoke_cli.commands.registry import resolve

    tokens, function_id, adapter, remaining = resolve(
        ["coordination-lease", "list", "--project", "yoke"]
    )
    assert tokens == ("coordination-lease", "list")
    assert function_id == "claims.coordination_lease.list"
    assert adapter is claims_coordination_lease_list
    assert remaining == ["--project", "yoke"]

    tokens, function_id, adapter, remaining = resolve(
        ["claims", "coordination-lease", "list", "--active-only"]
    )
    assert tokens == ("claims", "coordination-lease", "list")
    assert function_id == "claims.coordination_lease.list"
    assert adapter is claims_coordination_lease_list
    assert remaining == ["--active-only"]


def test_list_dispatches_filters_on_the_function_call_surface() -> None:
    captured: list[dict] = []

    def call_dispatcher(**kwargs):
        captured.append(kwargs)
        return FunctionCallResponse(
            success=True,
            function=kwargs["function_id"],
            version="v1",
            request_id="req-1",
            result={"leases": []},
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_cli.commands._helpers.call_dispatcher",
            side_effect=call_dispatcher,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(
                    io.StringIO()
                ):
                    result = cli_main([
                        "coordination-lease", "list",
                        "--project", "yoke",
                        "--key", "LIVE_DB_MIGRATION:primary",
                        "--session-id", "holder-session",
                        "--active-only",
                    ])

    assert result == 0
    assert captured
    request = captured[-1]
    assert request["function_id"] == "claims.coordination_lease.list"
    assert request["target"].kind == "global"
    assert request["payload"] == {
        "project_id": "yoke",
        "lease_key": "LIVE_DB_MIGRATION:primary",
        "session_id": "holder-session",
        "active_only": True,
    }
