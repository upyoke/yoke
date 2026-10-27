"""Tests for the machine-config writer function handlers.

``handle_project_register`` gates ``--reassign`` on the caller's live
steering seat covering the project whose checkout moves; a call without
that seat is refused before it ever reaches the writer. Registration
without ``--reassign`` needs no seat.
"""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import patch

import pytest

from runtime.api.domain.test_session_message_support import message_connection
from runtime.api.domain.test_steering_operation_authority import seat
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import machine_config_write as handlers


def _request(payload: dict, *, session_id: str = "") -> FunctionCallRequest:
    return FunctionCallRequest(
        function="project.register.run",
        actor=ActorContext(actor_id=None, session_id=session_id),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _register(request, *, seat_project=None):
    conn = message_connection()
    if seat_project is not None:
        seat(conn, project=seat_project)
    with (
        patch("yoke_core.domain.db_helpers.connect", return_value=nullcontext(conn)),
        patch.object(
            handlers.machine_config_writer,
            "register_project",
            return_value={"checkout": "/repo", "entry": {}, "config": "/cfg"},
        ) as mock_register,
    ):
        return handlers.handle_project_register(request), mock_register


@pytest.mark.parametrize("session_id,seat_project", [("s1", 2), ("s1", None), ("", 1)])
def test_reassign_without_a_covering_seat_is_refused(session_id, seat_project):
    outcome, mock_register = _register(
        _request(
            {"repo_root": "/repo", "project_id": 1, "reassign": True},
            session_id=session_id,
        ),
        seat_project=seat_project,
    )

    mock_register.assert_not_called()
    assert outcome.primary_success is False
    assert outcome.error.code == "steering_seat_required"
    assert "yoke claims steering acquire --project 1" in outcome.error.message


def test_reassign_with_the_project_steering_seat_proceeds():
    outcome, mock_register = _register(
        _request(
            {"repo_root": "/repo", "project_id": 1, "reassign": True},
            session_id="s1",
        ),
        seat_project=1,
    )

    mock_register.assert_called_once_with(
        "/repo",
        1,
        board_scope=None,
        board_render_path=None,
        reassign=True,
        path=None,
    )
    assert outcome.primary_success is True


def test_no_reassign_needs_no_seat():
    outcome, mock_register = _register(
        _request({"repo_root": "/repo", "project_id": 7}, session_id="s1")
    )

    mock_register.assert_called_once_with(
        "/repo",
        7,
        board_scope=None,
        board_render_path=None,
        reassign=False,
        path=None,
    )
    assert outcome.primary_success is True


def test_cli_reassign_reports_the_writer_refusal(tmp_path, capsys):
    from yoke_cli.commands.adapters import config_write_project as cli
    from yoke_cli.config import writer

    with patch.object(
        writer,
        "register_project",
        side_effect=writer.MachineConfigWriteError(
            "steering_seat_required: acquire the project seat"
        ),
    ) as register:
        result = cli.project_register(
            [
                str(tmp_path),
                "--project-id",
                "1",
                "--reassign",
            ]
        )
    assert result == 1
    assert "steering_seat_required" in capsys.readouterr().err
    assert register.call_args.kwargs["reassign"] is True
