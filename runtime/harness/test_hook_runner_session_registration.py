"""hook runner session registration regression coverage."""

# ruff: noqa: F401
from __future__ import annotations

import importlib
import json
from contextlib import contextmanager
from typing import Any
from yoke_contracts.session_identity import AMBIENT_ENV_VARS
import pytest
import yoke_core.hooks.registration as register_module
import yoke_core.hooks.telemetry as telemetry
from yoke_core.hooks import runner as runner_module
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.decision_render import render_claude_decision
from yoke_core.hooks.remote_policy import RunControls
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome

from runtime.harness.test_hook_runner_register_ensure import (
    _Mod,
    _allow,
    _run_runner,
    pytestmark,
)


class TestRunnerArmsEnsureSession:
    def test_tool_call_dispatch_arms_probe_with_payload_identity(
        self,
        monkeypatch,
    ):
        captured = _run_runner(
            monkeypatch,
            {
                "session_id": "s-tool",
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "transcript_path": "/t/z.jsonl",
            },
        )
        assert captured, "flush must run"
        sid, payload_json, *rest = captured[0]["ensure_session"]
        assert sid == "s-tool"
        # The MERGED payload rides the tuple (wire extras included), not
        # raw stdin.
        assert json.loads(payload_json)["transcript_path"] == "/t/z.jsonl"
        assert rest == ["/t/z.jsonl", True, "", True, False, None, None]

    def test_sessionless_payload_does_not_arm(self, monkeypatch, tmp_path):
        monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
        for name in (
            *AMBIENT_ENV_VARS,
            "CURSOR_CONVERSATION_ID",
            "CURSOR_TRANSCRIPT_PATH",
        ):
            monkeypatch.delenv(name, raising=False)
        captured = _run_runner(
            monkeypatch,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
            },
        )
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
        (
            session_id,
            payload_json,
            transcript,
            record_anchor,
            hint,
            in_process,
            force,
            actor_id,
            project_id,
        ) = captured[0]["ensure_session"]
        assert session_id == "s-remote"
        assert record_anchor is False
        assert in_process is True, "remote arming must register in-process"
        assert force is False, "tool-call relays never force re-registration"
        assert hint == "claude", (
            "remote arming must honor the request-built capability family"
        )
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
            telemetry,
            "flush_hook_telemetry",
            lambda records, *, deadline=None, ensure_session=None, observed_session=None: (
                captured.append(ensure_session)
            ),
        )
        capability = AdapterCapability(
            family="claude",
            payload_parser=lambda raw: {"session_id": "s-ss"},
            decision_renderer=render_claude_decision,
        )
        runner_module.run_event(
            "SessionStart",
            capability=capability,
            stdin_data="{}",
            controls=RunControls(remote=True),
        )
        assert captured and captured[0][6] is True
