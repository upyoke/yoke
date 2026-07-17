"""Ensure-register-on-first-sight coverage for the hook runner.

Locks the fix family for the live gap where a desktop session ran full
PreToolUse/PostToolUse chains all day with no ``harness_sessions`` row:
the dispatch telemetry flush probes for the session row on its shared
connection and drives the canonical ``_register_from_hook`` sequence
when (and only when) the row is positively missing. Also covers the
process-anchor write inside ``_register_from_hook`` and the runner-side
wiring that arms the probe for non-remote dispatches.
"""

from __future__ import annotations

import importlib
import json
from contextlib import contextmanager
from typing import Any
from unittest import mock

import pytest

import runtime.harness.hook_runner_register as register_module
import runtime.harness.hook_runner.telemetry as telemetry
from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import render_claude_decision
from runtime.harness.hook_runner.remote_policy import RunControls
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


# ---------------------------------------------------------------------------
# ensure_registered_from_hook
# ---------------------------------------------------------------------------


class TestEnsureRegisteredFromHook:
    def _patch_lookup(self, monkeypatch, found, stored_actor_id=None):
        monkeypatch.setattr(
            "yoke_core.domain.events_session_actor.session_actor_lookup",
            lambda _conn, _sid: (found, stored_actor_id),
        )

    def test_registers_when_row_positively_missing(self, monkeypatch):
        self._patch_lookup(monkeypatch, False)
        calls: list[tuple] = []
        monkeypatch.setattr(
            register_module, "_register_from_hook",
            lambda payload, sid, transcript_path="", record_anchor=True,
            executor_hint="", register_in_process=False,
            actor_id=None, project_id=None: calls.append(
                (payload, sid, transcript_path, record_anchor, executor_hint,
                 register_in_process, actor_id, project_id)
            ) or ("", "claude-code", "anthropic", "m", None),
        )
        drove = register_module.ensure_registered_from_hook(
            object(), '{"session_id": "s-1"}', "s-1",
            transcript_path="/t/x.jsonl",
        )
        assert drove is True
        assert calls == [
            ('{"session_id": "s-1"}', "s-1", "/t/x.jsonl", True, "", False, None, None),
        ]

    def test_remote_shape_suppresses_anchor_and_honors_executor(self, monkeypatch):
        self._patch_lookup(monkeypatch, False)
        calls: list[tuple] = []
        monkeypatch.setattr(
            register_module, "_register_from_hook",
            lambda payload, sid, transcript_path="", record_anchor=True,
            executor_hint="", register_in_process=False,
            actor_id=None, project_id=None: calls.append(
                (
                    sid, record_anchor, executor_hint, register_in_process,
                    actor_id, project_id,
                )
            ) or ("", "codex", "openai", "m", None),
        )
        drove = register_module.ensure_registered_from_hook(
            object(), "{}", "s-r",
            record_anchor=False, executor_hint="codex",
            register_in_process=True, actor_id=7, project_id=1,
        )
        assert drove is True
        assert calls == [("s-r", False, "codex", True, 7, 1)]

    def test_skips_when_row_exists(self, monkeypatch):
        self._patch_lookup(monkeypatch, True)
        monkeypatch.setattr(
            register_module, "_register_from_hook",
            lambda *a, **k: pytest.fail("must not register an existing session"),
        )
        assert (
            register_module.ensure_registered_from_hook(object(), "{}", "s-1")
            is False
        )

    def test_skips_when_lookup_failed(self, monkeypatch):
        # found=None means "could not verify" — a broken DB must not spawn
        # a registration subprocess per tool call.
        self._patch_lookup(monkeypatch, None)
        monkeypatch.setattr(
            register_module, "_register_from_hook",
            lambda *a, **k: pytest.fail("must not register on unknown state"),
        )
        assert (
            register_module.ensure_registered_from_hook(object(), "{}", "s-1")
            is False
        )

    def test_skips_blank_unknown_session_and_missing_conn(self):
        assert (
            register_module.ensure_registered_from_hook(object(), "{}", "")
            is False
        )
        assert (
            register_module.ensure_registered_from_hook(object(), "{}", "unknown")
            is False
        )
        assert (
            register_module.ensure_registered_from_hook(None, "{}", "s-1")
            is False
        )

    def test_register_failure_never_raises(self, monkeypatch):
        self._patch_lookup(monkeypatch, False)

        def _boom(*_a, **_k):
            raise RuntimeError("registration subprocess exploded")

        monkeypatch.setattr(register_module, "_register_from_hook", _boom)
        assert (
            register_module.ensure_registered_from_hook(object(), "{}", "s-1")
            is False
        )


# ---------------------------------------------------------------------------
# flush wiring: the shared connection drives the probe before records flush
# ---------------------------------------------------------------------------


class TestFlushEnsureSessionWiring:
    def test_flush_drives_ensure_with_shared_conn(self, monkeypatch):
        sentinel_conn = object()

        @contextmanager
        def fake_conn():
            yield sentinel_conn

        monkeypatch.setattr(
            "yoke_core.domain.events_writes.hook_emit_connection", fake_conn,
        )
        monkeypatch.setattr(
            "yoke_core.domain.events_writes.check_severity_conn",
            lambda *_a: True,
        )
        seen: list[tuple] = []
        monkeypatch.setattr(
            register_module, "ensure_registered_from_hook",
            lambda conn, payload, sid, transcript_path="", record_anchor=True,
            executor_hint="", register_in_process=False,
            force_reregister=False, actor_id=None, project_id=None: seen.append(
                (conn, payload, sid, transcript_path, record_anchor,
                 executor_hint, register_in_process, force_reregister, actor_id,
                 project_id)
            ),
        )
        telemetry.flush_hook_telemetry(
            [],
            ensure_session=(
                "s-77", '{"x":1}', "/t/y.jsonl", True, "", False, False, 5, 1,
            ),
        )
        assert seen == [
            (sentinel_conn, '{"x":1}', "s-77", "/t/y.jsonl", True, "",
             False, False, 5, 1),
        ]

    def test_flush_skips_ensure_without_connection(self, monkeypatch):
        @contextmanager
        def fake_conn():
            yield None

        monkeypatch.setattr(
            "yoke_core.domain.events_writes.hook_emit_connection", fake_conn,
        )
        monkeypatch.setattr(
            register_module, "ensure_registered_from_hook",
            lambda *a, **k: pytest.fail("no conn means no probe"),
        )
        telemetry.flush_hook_telemetry(
            [], ensure_session=("s-77", "{}", "", True, "", False, False, None, None),
        )

    def test_ensure_crash_never_breaks_flush(self, monkeypatch):
        @contextmanager
        def fake_conn():
            yield object()

        monkeypatch.setattr(
            "yoke_core.domain.events_writes.hook_emit_connection", fake_conn,
        )
        monkeypatch.setattr(
            "yoke_core.domain.events_writes.check_severity_conn",
            lambda *_a: True,
        )

        def _boom(*_a, **_k):
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(register_module, "ensure_registered_from_hook", _boom)
        flushed: list[dict[str, Any]] = []
        monkeypatch.setattr(
            telemetry, "emit_hook_dispatch_telemetry",
            lambda **k: flushed.append(k),
        )
        telemetry.flush_hook_telemetry(
            [(
                "dispatch",
                {
                    "hook_event": "PreToolUse", "executor": "claude",
                    "chain_length": 1, "decision_outcome": "allow",
                    "session_id": "s", "item_id": None, "tool_name": "Bash",
                    "duration_ms": 5,
                },
            )],
            ensure_session=("s-77", "{}", "", True, "", False, False, None, None),
        )
        assert len(flushed) == 1, "records must still flush after a probe crash"


# ---------------------------------------------------------------------------
# runner wiring: every event with a payload session arms the probe; remote
# evaluation registers the DB half only (no server-side anchor, executor honored)
# ---------------------------------------------------------------------------


def _allow(_context: HookContext) -> HookDecision:
    return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)


class _Mod:
    evaluate = staticmethod(_allow)


def _run_runner(monkeypatch, payload: dict, controls=None):
    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        return _Mod if name == "mod.allow" else real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: ["mod.allow"])
    captured: list[dict[str, Any]] = []

    def fake_flush(records, *, deadline=None, ensure_session=None):
        captured.append({"records": records, "ensure_session": ensure_session})

    monkeypatch.setattr(
        telemetry, "flush_hook_telemetry", fake_flush,
    )
    capability = AdapterCapability(
        family="claude",
        payload_parser=lambda raw: payload,
        decision_renderer=render_claude_decision,
    )
    runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="{}",
        controls=controls,
    )
    return captured


class TestRunnerArmsEnsureSession:
    def test_tool_call_dispatch_arms_probe_with_payload_identity(
        self, monkeypatch,
    ):
        captured = _run_runner(monkeypatch, {
            "session_id": "s-tool",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "transcript_path": "/t/z.jsonl",
        })
        assert captured, "flush must run"
        sid, payload_json, *rest = captured[0]["ensure_session"]
        assert sid == "s-tool"
        # The MERGED payload rides the tuple (wire extras included), not
        # raw stdin.
        assert json.loads(payload_json)["transcript_path"] == "/t/z.jsonl"
        assert rest == ["/t/z.jsonl", True, "", False, False, None, None]

    def test_sessionless_payload_does_not_arm(self, monkeypatch):
        captured = _run_runner(monkeypatch, {
            "tool_name": "Bash", "tool_input": {"command": "ls"},
        })
        assert captured[0]["ensure_session"] is None

    def test_remote_evaluation_arms_db_half_without_anchor(self, monkeypatch):
        # The relayed payload carries everything DB registration needs;
        # the request's executor is honored, the verified token actor rides
        # the tuple, and the server never writes its own anchor registry
        # (the caller's process tree is not the server's — the hook relay
        # writes the anchor client-side).
        controls = RunControls(remote=True, actor_id=3)
        captured = _run_runner(
            monkeypatch,
            {"session_id": "s-remote", "tool_name": "Bash"},
            controls=controls,
        )
        (session_id, payload_json, transcript, record_anchor, hint,
         in_process, force, actor_id, project_id) = captured[0]["ensure_session"]
        assert session_id == "s-remote"
        assert record_anchor is False
        assert in_process is True, "remote arming must register in-process"
        assert force is False, "tool-call relays never force re-registration"
        assert hint == "claude", "remote arming must honor the request-built capability family"
        assert actor_id == 3, "the verified token actor must ride the tuple"
        assert project_id is None


    def test_remote_registration_class_event_forces_reregister(self, monkeypatch):
        # SessionStart/UserPromptSubmit relays may carry a wire model; the
        # force path lets the registrar's SESSION_EXISTS branch upgrade a
        # stored placeholder even though the row already exists.
        real_import = importlib.import_module

        def fake_import(name):
            return _Mod if name == "mod.allow" else real_import(name)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: ["mod.allow"])
        captured = []
        monkeypatch.setattr(
            telemetry, "flush_hook_telemetry",
            lambda records, *, deadline=None, ensure_session=None:
                captured.append(ensure_session),
        )
        capability = AdapterCapability(
            family="claude",
            payload_parser=lambda raw: {"session_id": "s-ss"},
            decision_renderer=render_claude_decision,
        )
        runner_module.run_event(
            "SessionStart", capability=capability, stdin_data="{}",
            controls=RunControls(remote=True),
        )
        assert captured and captured[0][6] is True
