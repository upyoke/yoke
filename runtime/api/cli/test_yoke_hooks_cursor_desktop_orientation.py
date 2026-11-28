"""Windows Cursor Desktop first-prompt context at the CLI wire boundary."""

import io
import json
import subprocess
import sys
from types import SimpleNamespace

from runtime.api.cli.hook_relay_test_support import (
    https_connection as https_connection,
    local_subset as local_subset,
)
from runtime.api.cli.yoke_hooks_relay_orientation_test_support import _server_response
from runtime.api.cli.yoke_operations_cli_hooks_test_support import _FakeResponse, cli_main
from yoke_contracts.runtime_ports.identity import get_identity
from yoke_core.domain import session_orientation, session_orientation_delivery


def test_windows_cursor_desktop_prints_checkout_context_on_first_prompt(
    monkeypatch, tmp_path, capsys, bound_project_context, https_connection, local_subset
):
    branch = "picked-checkout"
    project = tmp_path / "picked-project"
    (project / ".yoke").mkdir(parents=True)
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch", branch, str(project)], check=True
    )
    transcript = tmp_path / "cursor.jsonl"
    transcript.touch()
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setenv("YOKE_EXECUTOR", "cursor")
    monkeypatch.delenv("CURSOR_INVOKED_AS", raising=False)
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
    monkeypatch.setattr(session_orientation, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *_a, **_k: _FakeResponse(_server_response())
    )
    assert get_identity().cursor_surface_entrypoint() == "cursor-desktop"
    workspace = project.as_posix()
    if sys.platform == "win32":
        workspace = "/" + workspace
    conversation_id = "a4bdac0b-7fac-429c-a162-f8d17dd765d8"
    payload = {
        "conversation_id": conversation_id,
        "session_id": conversation_id,
        "workspace_roots": [workspace],
        "transcript_path": str(transcript),
    }

    def evaluate(event, native_event, **extra):
        stdin = io.StringIO(json.dumps({**payload, "hook_event_name": native_event, **extra}))
        monkeypatch.setattr(sys, "stdin", stdin)
        assert cli_main(["hook", "evaluate", event]) == 0
        return json.loads(capsys.readouterr().out or "{}")

    startup = evaluate("SessionStart", "sessionStart")
    assert "Root:" not in startup.get("additional_context", "")
    assert "Current branch:" not in startup.get("additional_context", "")
    assert not session_orientation_delivery.orientation_delivered(conversation_id)

    prompt = evaluate("UserPromptSubmit", "beforeSubmitPrompt", prompt="What checkout is this?")
    context = prompt["additional_context"].splitlines()
    assert f"Your Session: {conversation_id}" in context
    assert f"Root: {project.resolve()}" in context
    assert f"Current branch: {branch}" in context
    assert session_orientation_delivery.orientation_delivered(conversation_id)

    next_prompt = evaluate("UserPromptSubmit", "beforeSubmitPrompt", prompt="Continue")
    assert f"Root: {project.resolve()}" not in next_prompt.get("additional_context", "")
