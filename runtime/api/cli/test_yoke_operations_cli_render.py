"""CLI adapter tests for ``yoke agents render``, ``yoke packets ...``,
and ``yoke board rebuild``."""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import List
from unittest.mock import ANY, patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.board import outcome as rb_outcome
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True, function=request.function, version=request.version,
        request_id=request.request_id, result={"echo": True},
    )


def _stub_fail(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=False, function=request.function, version=request.version,
        request_id=request.request_id,
        error=FunctionError(code="downstream_failure", message="stub"),
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(stub, *argv: str, session_id: str = "test-session") -> int:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch(
                "yoke_cli.commands._helpers.ensure_handlers_loaded"
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return cli_main(list(argv))


def _run_capture(stub, *argv: str, session_id: str = "test-session"):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch(
                "yoke_cli.commands._helpers.ensure_handlers_loaded"
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    rc = cli_main(list(argv))
    return rc, stdout.getvalue(), stderr.getvalue()


def _run_board_capture(result, *argv: str, repo_root: Path | None = None):
    stdout = io.StringIO()
    stderr = io.StringIO()
    root = repo_root or Path("/tmp/repo")
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_cli.board.rebuild.rebuild",
            return_value=result,
        ) as rebuild:
            with patch(
                "yoke_cli.board.rebuild.resolve_main_repo_root",
                return_value=root,
            ):
                with patch(
                    "yoke_core.cli.board_rebuild_timing_events.emit_event",
                ) as emit_event:
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        rc = cli_main(list(argv))
    return rc, stdout.getvalue(), stderr.getvalue(), rebuild, emit_event


class TestAgentsRender:
    def test_default_dispatches(self) -> None:
        rc = _run(_stub_ok, "agents", "render")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "agents.render.run"
        assert req.target.kind == "global"
        assert req.payload == {"dry_run": False}

    def test_dry_run_propagates(self) -> None:
        rc = _run(_stub_ok, "agents", "render", "--dry-run")
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload["dry_run"] is True

    def test_target_root_propagates(self) -> None:
        rc = _run(_stub_ok, "agents", "render", "--target-root", "/tmp/repo")
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload["target_root"] == "/tmp/repo"

    def test_check_resolves_three_token(self) -> None:
        rc = _run(_stub_ok, "agents", "render", "check")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "agents.render.check"


class TestPackets:
    def test_render_dispatches(self) -> None:
        rc = _run(_stub_ok, "packets", "render", "--role", "main_agent")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "packets.render.run"
        assert req.payload == {"role": "main_agent"}

    def test_render_missing_role_returns_two(self) -> None:
        rc = _run(_stub_ok, "packets", "render")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_check_dispatches(self) -> None:
        rc = _run(_stub_ok, "packets", "check")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "packets.check.run"
        assert req.payload == {}


class TestBoardRebuild:
    def test_default_invokes_local_rebuild(self) -> None:
        result = rb_outcome.rebuilt(Path("/tmp/BOARD.md"))
        rc, _stdout, _stderr, rebuild, _emit_event = _run_board_capture(
            result, "board", "rebuild",
        )

        assert rc == 0
        rebuild.assert_called_once_with(
            repo_arg="/tmp/repo",
            force=False,
            output_name=None,
            scope="all",
            emit=False,
            phase_recorder=ANY,
        )

    def test_force_propagates(self) -> None:
        result = rb_outcome.rebuilt(Path("/tmp/BOARD.md"))
        rc, _stdout, _stderr, rebuild, _emit_event = _run_board_capture(
            result, "board", "rebuild", "--force",
        )

        assert rc == 0
        assert rebuild.call_args.kwargs["force"] is True

    def test_repo_root_propagates(self) -> None:
        result = rb_outcome.rebuilt(Path("/tmp/BOARD.md"))
        rc, _stdout, _stderr, rebuild, _emit_event = _run_board_capture(
            result, "board", "rebuild", "--repo-root", "/tmp/repo",
        )

        assert rc == 0
        assert rebuild.call_args.kwargs["repo_arg"] == "/tmp/repo"

    def test_output_name_and_scope_propagate(self) -> None:
        result = rb_outcome.rebuilt(Path("/tmp/BOARD.epic.md"))
        rc, _stdout, _stderr, rebuild, _emit_event = _run_board_capture(
            result,
            "board", "rebuild",
            "--output-name", "BOARD.epic.md", "--scope", "epic",
        )

        assert rc == 0
        assert rebuild.call_args.kwargs["output_name"] == "BOARD.epic.md"
        assert rebuild.call_args.kwargs["scope"] == "epic"

    def test_rebuild_failure_prints_rebuild_detail(self) -> None:
        result = rb_outcome.failed(
            Path("/tmp/BOARD.md"),
            "Python board renderer failed: kaboom",
        )
        rc, stdout, stderr, _rebuild, emit_event = _run_board_capture(
            result, "board", "rebuild",
        )

        assert rc == 1
        assert stdout == ""
        assert "Python board renderer failed: kaboom" in stderr
        assert "yoke ouroboros field-note append" in stderr
        names = [call.args[0] for call in emit_event.call_args_list]
        assert names == ["BoardRebuildCommandStarted", "BoardRebuildCommandFailed"]
        failed = emit_event.call_args_list[-1].kwargs
        assert failed["duration_ms"] >= 0
        assert failed["exit_code"] == 1
        assert failed["severity"] == "WARN"
        assert failed["context"]["status"] == "failed"
        assert failed["context"]["message"] == "Python board renderer failed: kaboom"

    def test_human_mode_prints_status_not_json(self) -> None:
        result = rb_outcome.throttled(Path("/tmp/BOARD.md"), 5)

        rc, stdout, stderr, _rebuild, _emit_event = _run_board_capture(
            result, "board", "rebuild",
        )

        assert rc == 0
        assert stdout == "Board rebuild throttled: /tmp/BOARD.md\n"
        assert stderr == ""
        assert not stdout.lstrip().startswith("{")

    def test_rebuild_emits_command_timing_events(self) -> None:
        result = rb_outcome.rebuilt(Path("/tmp/BOARD.md"))

        rc, _stdout, _stderr, _rebuild, emit_event = _run_board_capture(
            result, "board", "rebuild", "--force",
        )

        assert rc == 0
        names = [call.args[0] for call in emit_event.call_args_list]
        assert names == ["BoardRebuildCommandStarted", "BoardRebuildCommandCompleted"]
        started = emit_event.call_args_list[0].kwargs
        completed = emit_event.call_args_list[1].kwargs
        assert started["event_kind"] == "workflow"
        assert started["event_type"] == "board_rebuild_command"
        assert started["tool_name"] == "yoke board rebuild"
        assert started["duration_ms"] is None
        assert started["context"]["started_at"]
        assert started["context"]["force"] is True
        assert completed["trace_id"] == started["trace_id"]
        assert completed["duration_ms"] >= 0
        assert completed["exit_code"] == 0
        assert completed["context"]["status"] == "rebuilt"
        assert completed["context"]["started_at"] == started["context"]["started_at"]
        assert completed["context"]["completed_at"]
        assert "phases_ms" in completed["context"]
        assert completed["context"]["print_mode"] == ""

    def test_json_mode_includes_command_timing(self) -> None:
        class _EmitResult:
            def __init__(self, event_id: str):
                self.event_id = event_id

        stdout = io.StringIO()
        stderr = io.StringIO()
        root = Path("/tmp/repo")
        result = rb_outcome.rebuilt(Path("/tmp/BOARD.md"))
        with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
            with patch(
                "yoke_cli.board.rebuild.rebuild",
                return_value=result,
            ):
                with patch(
                    "yoke_cli.board.rebuild.resolve_main_repo_root",
                    return_value=root,
                ):
                    with patch(
                        "yoke_core.cli.board_rebuild_timing_events.emit_event",
                        side_effect=[_EmitResult("start-id"), _EmitResult("end-id")],
                    ):
                        with redirect_stdout(stdout), redirect_stderr(stderr):
                            rc = cli_main(["board", "rebuild", "--json"])

        assert rc == 0
        assert stderr.getvalue() == ""
        envelope = json.loads(stdout.getvalue())
        assert envelope["event_ids"] == ["start-id", "end-id"]
        payload = envelope["result"]
        assert payload["started_at"]
        assert payload["completed_at"]
        assert payload["duration_ms"] >= 0
        assert payload["trace_id"]
        assert "phases_ms" in payload
        assert payload["print_mode"] == ""

    def test_operator_shell_without_session_rebuilds(self, tmp_path: Path) -> None:
        board_path = tmp_path / ".yoke" / "BOARD.md"

        def _fake_rebuild(**_kwargs):
            board_path.parent.mkdir(parents=True, exist_ok=True)
            board_path.write_text("line1\nline2\n", encoding="utf-8")
            return rb_outcome.rebuilt(board_path)

        env = {
            key: value for key, value in os.environ.items()
            if key not in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID")
        }
        with patch.dict("os.environ", env, clear=True):
            with patch(
                "yoke_cli.board.rebuild.rebuild",
                side_effect=_fake_rebuild,
            ):
                with patch(
                    "yoke_cli.board.rebuild.resolve_main_repo_root",
                    return_value=tmp_path,
                ):
                    with patch(
                        "yoke_core.cli.board_rebuild_timing_events.emit_event"
                    ):
                        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                            rc = cli_main(["board", "rebuild", "--force"])

        assert rc == 0
        assert board_path.is_file()
