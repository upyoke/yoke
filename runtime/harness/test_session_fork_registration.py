"""Saved forks keep their own identities; unsaved Codex turns stay unregistered."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_core.hooks import session_dispatch, session_dispatch_cursor
from yoke_core.hooks.types import HookContext

pytestmark = pytest.mark.usefixtures("bound_project_context")


def _context(family, payload):
    return HookContext("SessionStart", family, family, payload)


@pytest.mark.parametrize("family", ["claude", "codex", "cursor"])
def test_fork_start_registers_child_identity(tmp_path, monkeypatch, family):
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("CLAUDE_ENV_FILE", raising=False)
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    transcript = tmp_path / "child.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "id": "child",
                    "forked_from_id": "parent",
                },
            }
        )
        + "\n"
    )
    payload = {
        "session_id": "child",
        "hook_event_name": "sessionStart",
        "conversation_id": "child",
        "source": "fork",
        "forked_from_id": "parent",
        "transcript_path": str(transcript),
    }
    register = Mock(return_value="")
    facts = SessionModelFacts()
    context = _context(family, payload)
    if family == "codex":
        monkeypatch.setattr(session_dispatch, "_register_codex", register)
        monkeypatch.setattr(session_dispatch, "_codex_model_facts", lambda *a: facts)
        monkeypatch.setattr(
            "yoke_core.hooks.codex_model.resolve_entrypoint", lambda: "codex-desktop"
        )
        assert session_dispatch._run_codex_session_start(context, str(tmp_path)) == ""
        assert register.call_args.args[1] == "child"
        from yoke_core.hooks.codex_payload import read_runtime_cache_field

        assert read_runtime_cache_field("child", "source") == "fork"
        assert read_runtime_cache_field("child", "transcript_path") == str(transcript)
    elif family == "claude":
        monkeypatch.setattr(
            "yoke_core.hooks.registration._register_from_hook", register
        )
        session_dispatch._run_claude_session_start(context)
        assert register.call_args.args[1] == "child"
    else:
        payload["container_session_id"] = "child"
        monkeypatch.setattr(session_dispatch_cursor._lifecycle, "register", register)
        monkeypatch.setattr(session_dispatch_cursor, "_model_facts", lambda *a: facts)
        monkeypatch.setattr(
            session_dispatch_cursor, "_entrypoint", lambda: "cursor-desktop"
        )
        monkeypatch.setattr(
            session_dispatch_cursor, "_render_orientation", lambda *a: ""
        )
        session_dispatch_cursor.run_session_start(context, str(tmp_path))
        assert register.call_args.args[1] == "child"
    register.assert_called_once()


@pytest.mark.parametrize("payload_path", [False, True])
def test_unsaved_codex_prompt_is_quiet_and_can_retry_when_saved(
    tmp_path,
    monkeypatch,
    payload_path,
):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    directory = tmp_path / "sessions"
    directory.mkdir()
    transcript = directory / "rollout-child.jsonl"
    payload = {"session_id": "child", "forked_from_id": "parent"}
    if payload_path:
        payload["transcript_path"] = str(transcript)
    context = HookContext("UserPromptSubmit", "codex", "codex-desktop", payload)
    register = Mock(return_value="")
    prompt = Mock()
    monkeypatch.setattr(session_dispatch, "_register_codex", register)
    monkeypatch.setattr(
        session_dispatch, "_codex_model_facts", lambda *a: SessionModelFacts()
    )
    monkeypatch.setattr(
        "yoke_core.hooks.codex_model.resolve_entrypoint", lambda: "codex-desktop"
    )
    monkeypatch.setattr(
        "yoke_core.hooks.telemetry.emit_harness_session_sent_first_user_prompt_submit",
        prompt,
    )
    assert session_dispatch._run_codex_prompt_submit(context, str(tmp_path)) == ""
    register.assert_not_called()
    prompt.assert_not_called()
    transcript.touch()
    assert session_dispatch._run_codex_prompt_submit(context, str(tmp_path)) == ""
    assert register.call_args.args[1] == "child"
    register.assert_called_once()
    prompt.assert_called_once()
    assert session_dispatch._run_codex_prompt_submit(context, str(tmp_path)) == ""
    register.assert_called_once()


def test_unsaved_codex_prompt_never_reaches_registration_transport(
    tmp_path, monkeypatch, capsys
):
    from yoke_cli.commands.adapters import hook_inprocess

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(hook_inprocess, "_touch_detached_resume", lambda: None)
    monkeypatch.setattr("yoke_harness.hooks.identity.detect_executor", lambda: "codex")
    monkeypatch.setattr(
        "yoke_harness.hooks.command_workdir_stamp.stamp_command_workdir",
        lambda text, _: text,
    )
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: pytest.fail("unsaved turn reached transport selection"),
    )
    completed = Mock()
    assert (
        hook_inprocess.evaluate_inprocess(
            "UserPromptSubmit",
            json.dumps({"session_id": "child", "forked_from_id": "parent"}),
            dry_run=False,
            cursor_invocation=False,
            on_complete=completed,
        )
        == 0
    )
    completed.assert_called_once()
    assert capsys.readouterr() == ("", "")
