"""Tests for the machine-config writer function handlers.

``handle_project_register`` gates ``--reassign`` on ambient session
identity: any resolvable session id means a routine agent invocation
(every Dash/Engineer/Conduct/Tester worker has one by construction), so
the call is refused before it ever reaches the writer. A bare-terminal
call (no session id) needs no such check.
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.handlers import machine_config_write as handlers


def _request(payload: dict, *, session_id: str = "") -> FunctionCallRequest:
    return FunctionCallRequest(
        function="project.register.run",
        actor=ActorContext(actor_id=None, session_id=session_id),
        target=TargetRef(kind="global"),
        payload=payload,
    )


class TestHandleProjectRegister:
    def test_reassign_with_ambient_session_is_refused(self):
        request = _request(
            {"repo_root": "/repo", "project_id": 7, "reassign": True},
            session_id="sess-worker-1",
        )

        with patch.object(handlers.machine_config_writer, "register_project") as mock_register:
            outcome = handlers.handle_project_register(request)

        mock_register.assert_not_called()
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert "sess-worker-1" in outcome.error.message
        assert "--reassign refused" in outcome.error.message

    def test_reassign_with_no_ambient_session_proceeds(self):
        request = _request(
            {"repo_root": "/repo", "project_id": 7, "reassign": True},
            session_id="",
        )

        with patch.object(
            handlers.machine_config_writer, "register_project",
            return_value={"checkout": "/repo", "entry": {}, "config": "/cfg"},
        ) as mock_register:
            outcome = handlers.handle_project_register(request)

        mock_register.assert_called_once_with(
            "/repo", 7, board_scope=None, board_render_path=None,
            reassign=True, path=None,
        )
        assert outcome.primary_success is True

    def test_no_reassign_with_ambient_session_proceeds(self):
        request = _request(
            {"repo_root": "/repo", "project_id": 7},
            session_id="sess-worker-1",
        )

        with patch.object(
            handlers.machine_config_writer, "register_project",
            return_value={"checkout": "/repo", "entry": {}, "config": "/cfg"},
        ) as mock_register:
            outcome = handlers.handle_project_register(request)

        mock_register.assert_called_once_with(
            "/repo", 7, board_scope=None, board_render_path=None,
            reassign=False, path=None,
        )
        assert outcome.primary_success is True
