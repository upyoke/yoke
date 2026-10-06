"""Hook helpers import without a project and refuse scoped writes on demand."""

import importlib

import pytest

from yoke_contracts.project_defaults import MissingProjectError
from yoke_core.domain import project_scratch_dir
from yoke_core.hooks import helpers_markers


def test_import_does_not_resolve_project_paths(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("import attempted project-scoped resolution")

    monkeypatch.setattr(project_scratch_dir, "hook_marker_path", refuse)
    try:
        importlib.reload(helpers_markers)
    finally:
        monkeypatch.undo()
        importlib.reload(helpers_markers)


def test_unattributed_reads_are_empty_and_writes_refuse(monkeypatch):
    def refuse(*args, **kwargs):
        raise MissingProjectError("project_required: caller project missing")

    monkeypatch.setattr(helpers_markers, "hook_marker_path", refuse)
    assert helpers_markers.read_current_item_marker() == ""
    assert helpers_markers.read_done_item_marker() == ""
    with pytest.raises(MissingProjectError, match="project_required"):
        helpers_markers.write_current_item_marker(42)
    with pytest.raises(MissingProjectError, match="project_required"):
        helpers_markers.write_done_item_marker(42)


def test_unattributed_runtime_cache_read_is_empty(monkeypatch):
    from yoke_core.hooks import codex_payload

    def refuse(*args, **kwargs):
        raise MissingProjectError("project_required: caller project missing")

    monkeypatch.setattr(codex_payload, "runtime_cache_path", refuse)
    assert codex_payload.read_runtime_cache_field("session", "source") == ""


def test_unattributed_planning_scratch_has_no_allowed_roots(monkeypatch):
    from yoke_core.domain import path_claim_bash_parser_planning_phase as planning

    def refuse(*args, **kwargs):
        raise MissingProjectError("project_required: caller project missing")

    monkeypatch.setattr(project_scratch_dir, "dispatch_inputs_dir", refuse)
    assert planning.planning_scratch_roots() == ()


def test_unattributed_model_and_entrypoint_cache_reads_are_empty(monkeypatch):
    from yoke_core.hooks import codex_model

    def refuse(*args, **kwargs):
        raise MissingProjectError("project_required: caller project missing")

    monkeypatch.setattr(codex_model, "_runtime_cache_path", refuse)
    assert codex_model.resolve_from_cache("thread") is None
    assert codex_model.resolve_entrypoint_from_cache("thread") is None


def test_polling_lint_import_has_no_project_or_filesystem_resolution(monkeypatch):
    from yoke_core.domain import lint_long_command_polling_extract as extract

    def refuse(*args, **kwargs):
        raise AssertionError("classification attempted scratch write resolution")

    monkeypatch.setattr(project_scratch_dir, "scratch_root", refuse)
    monkeypatch.setattr(project_scratch_dir, "global_scratch_root", refuse)
    importlib.reload(extract)
    assert extract._TEMP_PREFIXES


def test_command_capture_uses_case_project_instead_of_server_context(
    tmp_path, monkeypatch
):
    from yoke_core.domain.qa_case_command_stream import stream_command

    monkeypatch.setenv("YOKE_PROJECT", "8")
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    result = stream_command(
        "printf caller-output",
        cwd=str(tmp_path),
        env={"YOKE_PROJECT": "7"},
        timeout_seconds=10,
    )
    assert result.exit_code == 0
    assert "7" in result.capture_path.parts
    assert "8" not in result.capture_path.parts


def test_dispatch_handler_refuses_missing_payload_project_before_path_resolution(
    monkeypatch,
):
    from contextlib import nullcontext
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain import db_helpers, project_selection
    from yoke_core.domain.handlers import scratch_dispatch_inputs as handler

    monkeypatch.setenv("YOKE_PROJECT", "server-project")
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(object()))
    monkeypatch.setattr(
        project_selection,
        "missing_project_on_connection",
        lambda conn, actor_id: "project_required: Accessible projects: caller-project",
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("missing payload reached project-scoped path resolver")

    monkeypatch.setattr(handler, "dispatch_inputs_dir", forbidden)
    outcome = handler.handle_dispatch_inputs(
        FunctionCallRequest(
            function="scratch.dispatch_inputs",
            actor=ActorContext(actor_id="2", session_id="s"),
            target=TargetRef(kind="global"),
            payload={"item_id": 42, "session_id": "s", "attempt": 1},
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == "project_required"
    assert "caller-project" in outcome.error.message


@pytest.mark.parametrize("streaming_pair", [False, True])
def test_unbound_watcher_refuses_without_traceback(monkeypatch, capsys, streaming_pair):
    from argparse import Namespace
    from yoke_core.tools import _watch_capture_binding, _watch_runner

    def refuse(*args, **kwargs):
        raise MissingProjectError(
            "project_required: no project given — pass --project P. "
            "Accessible projects: platform, yoke."
        )

    monkeypatch.setattr(_watch_capture_binding, "mint_watcher_capture_pair", refuse)
    with pytest.raises(SystemExit) as outcome:
        if streaming_pair:
            _watch_runner.mint_capture_paths("pytest")
        else:
            _watch_runner.bind_capture_paths(Namespace(), "pytest")
    assert outcome.value.code == 2
    message = capsys.readouterr().err
    assert "project_required" in message
    assert "YOKE_PROJECT=P" in message
    assert "platform, yoke" in message
    assert "Traceback" not in message
    assert "--project" not in message
