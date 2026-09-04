"""Focused CLI dispatch tests for session/orchestration wrappers."""

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


def _stub_dispatch_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"echo": True},
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(*argv: str, session_id: str = "test-session") -> int:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_dispatch_ok,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                buf = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(buf), redirect_stderr(err):
                    return cli_main(list(argv))


def test_sessions_touch_dispatches() -> None:
    assert _run("sessions", "touch", "--mode", "charge") == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.touch"
    assert req.target.kind == "global"
    assert req.payload == {"mode": "charge"}


def test_sessions_touch_dispatches_reason_without_a_mode() -> None:
    assert (
        _run(
            "sessions",
            "touch",
            "--reason",
            "waiting on merge queue",
        )
        == 0
    )
    req = _CAPTURED_REQUESTS[-1]
    assert req.payload == {"reason": "waiting on merge queue"}


def test_sessions_identity_dispatches_with_empty_payload() -> None:
    assert _run("sessions", "identity") == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.identity"
    assert req.target.kind == "global"
    assert req.payload == {}


def test_sessions_checkpoint_dispatches() -> None:
    assert (
        _run(
            "sessions",
            "checkpoint",
            "--step",
            "2",
            "--action",
            "charge",
            "--chainable",
            "true",
            "--item-id",
            "42",
            "--task-num",
            "3",
            "--outcome",
            "completed",
            "--status",
            "implemented",
            "--required-path",
            "runtime/api/foo.py",
            "--pre-status",
            "implementing",
            "--failure-class",
            "dirty-tracked-main",
        )
        == 0
    )
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.checkpoint"
    assert req.target.kind == "global"
    assert req.payload == {
        "step": 2,
        "action": "charge",
        "chainable": True,
        "outcome": "completed",
        "item_id": "42",
        "task_num": 3,
        "status": "implemented",
        "required_path": "runtime/api/foo.py",
        "pre_status": "implementing",
        "failure_class": "dirty-tracked-main",
    }


def test_sessions_checkpoint_read_dispatches() -> None:
    assert _run("sessions", "checkpoint-read") == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.checkpoint_read"
    assert req.target.kind == "global"
    assert req.payload == {}


def test_sessions_offer_dispatches_with_explicit_session() -> None:
    assert (
        _run(
            "sessions",
            "offer",
            "--step",
            "2",
            "--project",
            "yoke",
            "--session-id",
            "offer-session",
        )
        == 0
    )
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.offer"
    assert req.actor.session_id == "offer-session"
    assert req.target.kind == "global"
    assert req.payload == {"step": 2, "project": "yoke"}


def test_sessions_offer_rejects_caller_asserted_identity() -> None:
    """No identity flag survives on the offer surface.

    A caller-supplied lane is the mechanism by which a locally guessed value
    outranks the session row, so the surface must not accept one — nor any
    other field the row already answers.
    """
    for flag, value in (
        ("--executor", "codex"),
        ("--provider", "openai"),
        ("--workspace", "/tmp/workspace"),
        ("--model", "some-model"),
        ("--supported-paths", "advance"),
    ):
        assert _run("sessions", "offer", flag, value) == 2


def test_sessions_ownership_guard_dispatches_item_ref() -> None:
    assert (
        _run(
            "sessions",
            "ownership-guard",
            "--item",
            "42",
            "--project",
            "yoke",
        )
        == 0
    )
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.ownership_guard"
    assert req.target.kind == "item"
    assert req.target.public_ref == "42"
    assert req.target.project_id == "yoke"
    assert req.payload == {}


def test_charge_schedule_dispatches() -> None:
    assert (
        _run(
            "charge",
            "schedule",
            "--project",
            "yoke",
            "--wip-cap",
            "7",
        )
        == 0
    )
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "charge.schedule"
    assert req.target.kind == "global"
    assert req.payload["project"] == "yoke"
    assert req.payload["wip_cap"] == 7
    assert req.payload["workspace"]


def test_registry_maps_sessions_list_to_function_id() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("sessions", "list")][0] == "sessions.list"


def test_session_closeout_and_reclaim_dispatch() -> None:
    assert _run("sessions", "end-if-empty", "--triggered-by", "hook") == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "sessions.end_if_empty"
    assert request.payload == {"triggered_by": "hook"}

    assert (
        _run(
            "sessions",
            "reclaim-stale",
            "--confirm",
            "--project-ids",
            "1,3",
        )
        == 0
    )
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "sessions.reclaim_stale"
    assert request.payload == {"confirm": True, "project_ids": [1, 3]}


def test_sessions_list_dispatches_filters_and_prints_roster_table() -> None:
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "fields": ["session_id", "liveness", "mode", "claims"],
                "rows": [
                    {
                        "session_id": "s-1",
                        "liveness": "active",
                        "mode": "charge",
                        "claims": [
                            {"target_kind": "item", "target": "YOK-41"},
                            {"target_kind": "process", "target": "feed"},
                        ],
                    },
                ],
            },
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                out = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = cli_main(
                        [
                            "sessions",
                            "list",
                            "--project",
                            "yoke",
                            "--liveness",
                            "active",
                            "--limit",
                            "5",
                        ]
                    )

    assert rc == 0
    lines = out.getvalue().splitlines()
    assert lines[:3] == [
        "SESSIONS",
        "SESSION  PROJECT  FOCUS         ROLE  RUNNER  MACHINE  LIVENESS  RESUME  RELAY  MESSAGEABLE  DIAGNOSTICS",
        "-------  -------  ------------  ----  ------  -------  --------  ------  -----  -----------  -----------",
    ]
    assert lines[3] == (
        "s-1      —        YOK-41, feed  —     —       —        active    —       —      unknown      —"
    )
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.list"
    assert req.target.kind == "global"
    assert req.payload == {
        "project": "yoke",
        "liveness": "active",
        "limit": 5,
    }
