"""CLI contract for opening an exact stage private-route grant."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.api.service_client_structured_api_adapter import adapter_for

from .session_control_qualification import QUALIFICATION_OPEN_USAGE


RELEASE_SHA = "a" * 40


def test_open_inventory_is_operator_only_and_names_the_real_cli() -> None:
    entry = adapter_for("session_control.qualification.open")

    assert entry is not None
    assert entry.cli_invocation == QUALIFICATION_OPEN_USAGE
    assert entry.agent_path == "operator-only"


@patch(
    "yoke_cli.commands.adapters.session_control_qualification.is_subagent_execution",
    return_value=False,
)
def test_open_dispatches_exact_stage_scope_and_redacts_human_output(
    _execution,
) -> None:
    captured: list[dict] = []

    def call_dispatcher(**kwargs):
        captured.append(kwargs)
        return FunctionCallResponse(
            success=True,
            function=kwargs["function_id"],
            version="v1",
            request_id="request-1",
            result={
                "grant": {
                    "lease_id": 81,
                    "grant_digest": "d" * 64,
                    "expires_at": "2026-08-23T01:30:00Z",
                    "sender_session_id": "must-not-print",
                    "scope": {"release_sha": RELEASE_SHA},
                }
            },
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "operator-session"}):
        with patch(
            "yoke_cli.commands._helpers.call_dispatcher",
            side_effect=call_dispatcher,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = cli_main(
                        [
                            "session-control",
                            "qualification",
                            "open",
                            "--project",
                            "yoke",
                            "--release-sha",
                            RELEASE_SHA,
                            "--run-id",
                            "stage-proof-1",
                            "--surface",
                            "claude-cli",
                            "--version",
                            "2.1.241",
                            "--operation",
                            "message_stopped",
                            "--route",
                            "direct",
                        ]
                    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert stdout.getvalue().strip() == (
        "qualification lease=81 digest=" + "d" * 64 + " expires=2026-08-23T01:30:00Z"
    )
    assert "must-not-print" not in stdout.getvalue()
    assert RELEASE_SHA not in stdout.getvalue()
    request = captured[-1]
    assert request["function_id"] == "session_control.qualification.open"
    assert request["target"].kind == "global"
    assert request["actor"].session_id == "operator-session"
    assert request["payload"] == {
        "project": "yoke",
        "environment": "stage",
        "release_sha": RELEASE_SHA,
        "acceptance_run_id": "stage-proof-1",
        "surface": "claude-cli",
        "version": "2.1.241",
        "operation": "message_stopped",
        "route": "direct",
    }


def test_subagent_cannot_open_operator_qualification() -> None:
    stderr = io.StringIO()
    with patch(
        "yoke_cli.commands.adapters.session_control_qualification."
        "is_subagent_execution",
        return_value=True,
    ):
        with patch(
            "yoke_cli.commands._helpers.call_dispatcher",
            side_effect=AssertionError("must not dispatch"),
        ):
            with redirect_stderr(stderr):
                code = cli_main(
                    [
                        "session-control",
                        "qualification",
                        "open",
                        "--project",
                        "yoke",
                        "--release-sha",
                        RELEASE_SHA,
                        "--run-id",
                        "stage-proof-child",
                        "--surface",
                        "claude-cli",
                        "--version",
                        "2.1.241",
                        "--operation",
                        "message_stopped",
                        "--route",
                        "direct",
                    ]
                )

    assert code == 2
    assert "subagents cannot open Fleet qualification grants" in stderr.getvalue()
