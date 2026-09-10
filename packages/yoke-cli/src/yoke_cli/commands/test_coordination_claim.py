"""Tests for the human-only coordination-claim recovery command."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.coordination_claim_recovery import OPERATOR_RELEASE_USAGE


def test_help_teaches_hosted_operator_recovery(capsys) -> None:
    assert cli_main(["coordination-claim", "release", "--help"]) == 0
    captured = capsys.readouterr()
    assert OPERATOR_RELEASE_USAGE in captured.out
    assert "works through HTTPS or local authority" in captured.out
    assert "signed-in human action" in captured.out
    assert "agent sessions are refused" in captured.out
    assert "--claim-id" in captured.out
    assert "--holder-session-id" in captured.out
    assert "--session-id" not in captured.out
    assert captured.err == ""


def test_public_release_routes_to_registered_operator_function() -> None:
    from yoke_cli.commands.adapters.claims_coordination_claim import (
        claims_coordination_claim_operator_release,
    )
    from yoke_cli.commands.registry import resolve

    tokens, function_id, adapter, remaining = resolve(
        ["coordination-claim", "release", "--project", "yoke"]
    )
    assert tokens == ("coordination-claim", "release")
    assert function_id == "claims.coordination_claim.operator_release"
    assert adapter is claims_coordination_claim_operator_release
    assert remaining == ["--project", "yoke"]


def test_public_release_dispatches_exact_reviewed_holder() -> None:
    captured: list[dict] = []

    def call_dispatcher(**kwargs):
        captured.append(kwargs)
        return FunctionCallResponse(
            success=True,
            function=kwargs["function_id"],
            version="v1",
            request_id="req-1",
            result={"released": True},
        )

    with (
        patch(
            "yoke_cli.commands._helpers.call_dispatcher",
            side_effect=call_dispatcher,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
    ):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = cli_main(
                [
                    "coordination-claim",
                    "release",
                    "--project",
                    "yoke",
                    "--key",
                    "DEPLOY:yoke",
                    "--claim-id",
                    "42",
                    "--holder-session-id",
                    "stranded-session",
                    "--reason",
                    "driver exited after pipeline settled",
                    "--json",
                ]
            )

    assert result == 0
    assert captured[-1]["function_id"] == ("claims.coordination_claim.operator_release")
    assert captured[-1]["payload"] == {
        "project_id": "yoke",
        "key": "DEPLOY:yoke",
        "claim_id": 42,
        "holder_session_id": "stranded-session",
        "reason": "driver exited after pipeline settled",
    }


def test_function_call_list_wins_over_tool_shaped_group() -> None:
    from yoke_cli.commands.adapters.claims_coordination_claim import (
        claims_coordination_claim_list,
    )
    from yoke_cli.commands.registry import resolve

    tokens, function_id, adapter, remaining = resolve(
        ["coordination-claim", "list", "--project", "yoke"]
    )
    assert tokens == ("coordination-claim", "list")
    assert function_id == "claims.coordination_claim.list"
    assert adapter is claims_coordination_claim_list
    assert remaining == ["--project", "yoke"]

    tokens, function_id, adapter, remaining = resolve(
        ["claims", "coordination-claim", "list", "--active-only"]
    )
    assert tokens == ("claims", "coordination-claim", "list")
    assert function_id == "claims.coordination_claim.list"
    assert adapter is claims_coordination_claim_list
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
            result={"claims": []},
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_cli.commands._helpers.call_dispatcher",
            side_effect=call_dispatcher,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    result = cli_main(
                        [
                            "coordination-claim",
                            "list",
                            "--project",
                            "yoke",
                            "--key",
                            "LIVE_DB_MIGRATION:primary",
                            "--session-id",
                            "holder-session",
                            "--active-only",
                        ]
                    )

    assert result == 0
    assert captured
    request = captured[-1]
    assert request["function_id"] == "claims.coordination_claim.list"
    assert request["target"].kind == "global"
    assert request["payload"] == {
        "project_id": "yoke",
        "key": "LIVE_DB_MIGRATION:primary",
        "session_id": "holder-session",
        "active_only": True,
    }


def test_list_dispatches_item_filter_on_the_function_call_surface() -> None:
    captured: list[dict] = []

    def call_dispatcher(**kwargs):
        captured.append(kwargs)
        return FunctionCallResponse(
            success=True,
            function=kwargs["function_id"],
            version="v1",
            request_id="req-1",
            result={"claims": []},
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_cli.commands._helpers.call_dispatcher",
            side_effect=call_dispatcher,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    result = cli_main(
                        [
                            "coordination-claim",
                            "list",
                            "--item",
                            "42",
                        ]
                    )

    assert result == 0
    assert captured[-1]["payload"] == {"owner_item_id": 42}
