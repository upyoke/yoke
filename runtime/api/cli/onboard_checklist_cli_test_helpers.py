"""Shared harness for ``yoke onboard checklist`` CLI adapter tests.

The adapter tests stub the dispatcher and assert on the captured
``FunctionCallRequest`` kwargs; this module owns the canned result
payloads and the capture-run helper so the init- and run-focused test
modules stay under the authored-file line cap without duplicating the
harness.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from yoke_cli import main as yoke_operations_cli
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)


def checklist_row(
    row_id: str,
    status: str,
    *,
    evidence: Any = "",
    blocker: str = "",
    note: str = "",
) -> dict[str, Any]:
    return {
        "row_id": row_id,
        "step": "2",
        "title": "Machine profile",
        "layer": "machine",
        "owner": "yoke onboard",
        "status": status,
        "hint": "Create ~/.yoke and secret storage.",
        "evidence": evidence,
        "blocker": blocker,
        "note": note,
    }


def run_result(**updates: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 1,
        "operation": "onboard.checklist.run",
        "run_id": "run-test",
        "resumed": False,
        "branch": "machine-only",
        "project_id": 7,
        "project_slug": "demo",
        "github_repo": "owner/repo",
        "checkout_path": "/project",
        "status": "blocked",
        "rows": [
            checklist_row(
                "machine-profile",
                "verified",
                evidence={"message": "dispatcher evidence"},
            ),
            checklist_row(
                "machine-github-connection",
                "blocked",
                blocker="missing org grant",
            ),
        ],
        "summary": {
            "status": "blocked",
            "open_rows": ["machine-github-connection"],
            "blocked_rows": ["machine-github-connection"],
        },
    }
    result.update(updates)
    return result


def init_result(**updates: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 1,
        "operation": "onboard.checklist.init",
        "run_id": "run-init",
        "resumed": False,
        "machine_config_path": "/home/config.json",
        "checkout_path": "/checkout",
        "project_id": 7,
        "status": "open",
        "rows": [checklist_row("machine-profile", "needed")],
        "summary": {
            "status": "open",
            "open_rows": ["machine-profile"],
            "blocked_rows": [],
        },
    }
    result.update(updates)
    return result


def dispatch_response(
    kwargs: dict[str, Any], result: dict[str, Any]
) -> FunctionCallResponse:
    request = FunctionCallRequest(
        function=kwargs["function_id"],
        actor=kwargs.get("actor") or ActorContext(session_id=""),
        target=kwargs.get("target") or TargetRef(kind="global"),
        payload=kwargs.get("payload") or {},
    )
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result=result,
    )


def run_cli(
    argv: list[str],
    *,
    result: dict[str, Any],
) -> tuple[int, list[dict[str, Any]]]:
    """Run the CLI with a stubbed dispatcher; return (rc, captured calls)."""
    calls: list[dict[str, Any]] = []

    def stub_call_dispatcher(**kwargs: Any) -> FunctionCallResponse:
        calls.append(kwargs)
        return dispatch_response(kwargs, result)

    with patch("yoke_cli.commands.adapters.onboard_checklist.ensure_handlers_loaded"):
        with patch(
            "yoke_cli.commands.adapters.onboard_checklist.call_dispatcher",
            side_effect=stub_call_dispatcher,
        ):
            rc = yoke_operations_cli.main(argv)
    return rc, calls


__all__ = [
    "checklist_row",
    "dispatch_response",
    "init_result",
    "run_cli",
    "run_result",
]
