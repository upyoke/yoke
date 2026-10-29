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


@pytest.mark.parametrize("source", ["startup", "resume", "fork", "clear", "compact"])
@pytest.mark.parametrize("transcript_path", [None, "", "saved.jsonl"])
def test_codex_start_gates_before_registration_transport(
    monkeypatch, source, transcript_path
):
    import sqlite3
    from yoke_cli.commands.adapters import hook_inprocess

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE harness_sessions (session_id TEXT)")
    monkeypatch.setattr(hook_inprocess, "_touch_detached_resume", lambda: None)
    monkeypatch.setattr("yoke_harness.hooks.identity.detect_executor", lambda: "codex")
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_codex_runtime.codex_transcript_exists",
        lambda *a: pytest.fail("SessionStart must not scan transcripts"),
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.command_workdir_stamp.stamp_command_workdir",
        lambda text, _: text,
    )
    transport = Mock(return_value=object())
    monkeypatch.setattr("yoke_cli.transport.https.resolve_https_connection", transport)
    monkeypatch.setattr(hook_inprocess, "_session_orientation", lambda *a, **k: "")

    def relay(event, connection, *, stdin_data, **kwargs):
        payload = json.loads(stdin_data)
        conn.execute("INSERT INTO harness_sessions VALUES (?)", (payload["session_id"],))
        return 0

    relayed = Mock(side_effect=relay)
    monkeypatch.setattr("yoke_harness.hooks.relay.relay_hook_event", relayed)
    completed = Mock()
    assert hook_inprocess.evaluate_inprocess(
        "SessionStart",
        json.dumps({"session_id": "child", "source": source,
                    "transcript_path": transcript_path}),
        dry_run=False, cursor_invocation=False, on_complete=completed,
    ) == 0
    assert conn.execute("SELECT session_id FROM harness_sessions").fetchall() == (
        [("child",)] if transcript_path else []
    )
    assert relayed.call_count == transport.call_count == bool(transcript_path)
    completed.assert_called_once()
    conn.close()


def _ensure(monkeypatch, *, found, ended=False, stored_actor_id=None, **kwargs):
    from yoke_core.hooks import registration

    monkeypatch.setattr(
        "yoke_core.domain.sessions_ended_recovery.session_registration_state",
        lambda _conn, _sid: (found, stored_actor_id, ended),
    )
    monkeypatch.setattr(registration, "placeholder_identity_can_upgrade", lambda *a: False)
    registered = []
    monkeypatch.setattr(
        registration,
        "_register_from_hook",
        lambda payload, sid, **kw: registered.append((sid, kw.get("actor_id"))),
    )
    drove = registration.ensure_registered_from_hook(
        object(), "{}", "helper", register_in_process=True, **kwargs
    )
    return drove, registered


@pytest.mark.parametrize(
    "found,ended,force",
    [(False, False, False), (True, True, False), (True, False, True)],
    ids=["missing", "ended", "force_reregister"],
)
def test_unsaved_codex_hook_never_creates_or_revives_a_row(
    monkeypatch, found, ended, force
):
    assert _ensure(
        monkeypatch, found=found, ended=ended,
        executor_hint="codex-desktop", force_reregister=force,
    ) == (False, [])


@pytest.mark.parametrize(
    "executor,transcript_path",
    [("codex-desktop", "/saved/helper.jsonl"), ("claude-desktop", "")],
)
def test_saved_codex_and_claude_without_a_path_still_register(
    monkeypatch, executor, transcript_path
):
    assert _ensure(
        monkeypatch, found=False,
        executor_hint=executor, transcript_path=transcript_path,
    ) == (True, [("helper", None)])


def test_live_unsaved_codex_row_still_gets_its_actor_backfilled(monkeypatch):
    assert _ensure(
        monkeypatch, found=True, executor_hint="codex-desktop", actor_id=7,
    ) == (True, [("helper", 7)])


def test_unsaved_codex_helper_tool_call_is_allowed_unregistered(monkeypatch):
    from yoke_contracts.hook_runner import guard_scope, project_scope
    from yoke_core.hooks import registration, run_tail, runner
    from yoke_core.hooks.adapter_capability import AdapterCapability
    from yoke_core.hooks.decision_render import render_codex_decision
    from yoke_core.hooks.types import HookDecision, Outcome

    monkeypatch.setenv("YOKE_EXECUTOR", "codex-desktop")
    monkeypatch.setattr(
        project_scope, "resolve_hook_project_scope",
        lambda payload: type("Scope", (), {"require_project_id": lambda self: 1})(),
    )
    monkeypatch.setattr(guard_scope, "applicable_chain", lambda chain, project: chain)
    monkeypatch.setattr(runner, "record_guard_decision", lambda *a, **kw: None)
    monkeypatch.setattr(runner._mode_gate, "apply_mode", lambda d, *a, **kw: d)
    monkeypatch.setattr(
        runner, "invoke_module",
        lambda module, **kw: (HookDecision(outcome=Outcome.NOOP), "", None, (module, {})),
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_ended_recovery.session_registration_state",
        lambda _conn, _sid: (False, None, False),
    )
    monkeypatch.setattr(
        registration, "_register_from_hook",
        lambda *a, **k: pytest.fail("unsaved Codex helper registered"),
    )
    driven = []

    def tail(**kw):
        request = run_tail._ensure_session_request(
            event_name=kw["event_name"], context=kw["context"],
            payload=kw["payload"], stdin_data=kw["stdin_data"],
            controls=kw["controls"], preflight_complete=False,
        )
        session_id, payload_json, transcript, anchor, hint, *_ = request
        driven.append(registration.ensure_registered_from_hook(
            object(), payload_json, session_id, transcript_path=transcript,
            record_anchor=anchor, executor_hint=hint, register_in_process=True,
        ))

    monkeypatch.setattr(run_tail, "flush_run_tail", tail)
    payload = {"session_id": "helper", "tool_name": "Bash",
               "tool_input": {"command": "ls"}}
    capability = AdapterCapability(
        family="codex", payload_parser=json.loads,
        decision_renderer=render_codex_decision,
    )

    text, code = runner.run_event(
        "PreToolUse", capability=capability, stdin_data=json.dumps(payload)
    )

    assert code == 0
    assert "BLOCKED" not in text
    assert driven == [False]
