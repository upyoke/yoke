"""Ensure-register revives a session whose row a transient end closed.

The sleep/resume path: Claude Desktop and Codex both fire an end on
transient signals (laptop sleep, app reload, brief disconnect) and then
keep the same conversation running under the same ``session_id``. If
revival waits for ``SessionStart`` / ``UserPromptSubmit``, an agentic
turn that continues past the end never submits a new prompt, so every
registered surface refuses ``SESSION_ENDED`` for the rest of the turn.

Tool-call hooks are the only empirically guaranteed event class, so the
ensure-register probe must treat an *ended* row exactly like a missing
one and drive ``_register_from_hook`` into the registrar's reactivation
branch. Both harnesses are covered here because both reach this path:
the local client shape and the relayed server-side (``register_in_process``)
shape a no-checkout Codex machine uses.

The missing-row, live-row, and unknown-lookup cases live in
``test_hook_runner_register_ensure.py``.
"""

from __future__ import annotations

import pytest

import yoke_core.hooks.registration as register_module


def _patch_state(monkeypatch, *, found, stored_actor_id=None, ended=False):
    monkeypatch.setattr(
        "yoke_core.domain.sessions_ended_recovery.session_registration_state",
        lambda _conn, _sid: (found, stored_actor_id, ended),
    )


def _capture_register(monkeypatch, calls, executor, provider):
    monkeypatch.setattr(
        register_module, "_register_from_hook",
        lambda payload, sid, transcript_path="", record_anchor=True,
        executor_hint="", register_in_process=False,
        actor_id=None, project_id=None: calls.append(
            (sid, record_anchor, executor_hint, register_in_process,
             actor_id, project_id)
        ) or ("", executor, provider, "m", None),
    )


class TestEndedRowDrivesRevival:
    def test_local_tool_call_revives_ended_row(self, monkeypatch):
        # "A row exists" is not enough to short-circuit: this hook event is
        # itself proof the harness process is alive.
        _patch_state(monkeypatch, found=True, stored_actor_id=4, ended=True)
        calls: list[tuple] = []
        _capture_register(monkeypatch, calls, "claude-code", "anthropic")
        monkeypatch.setattr(
            register_module, "placeholder_identity_can_upgrade",
            lambda *_a, **_k: pytest.fail(
                "an ended row needs no identity-upgrade probe to revive"
            ),
        )

        drove = register_module.ensure_registered_from_hook(
            object(), '{"session_id": "s-1"}', "s-1",
        )

        assert drove is True
        assert calls == [("s-1", True, "", False, None, None)]

    def test_relayed_codex_tool_call_revives_ended_row(self, monkeypatch):
        # Codex parity: the desktop continuation keeps the same ambient
        # session id after its row ended, and on a no-checkout machine the
        # relayed server-side evaluation is the DB-effective half.
        _patch_state(monkeypatch, found=True, stored_actor_id=7, ended=True)
        calls: list[tuple] = []
        _capture_register(monkeypatch, calls, "codex", "openai")

        drove = register_module.ensure_registered_from_hook(
            object(), "{}", "s-codex",
            record_anchor=False, executor_hint="codex",
            register_in_process=True, actor_id=7, project_id=1,
        )

        assert drove is True
        assert calls == [("s-codex", False, "codex", True, 7, 1)]

    def test_live_row_still_short_circuits(self, monkeypatch):
        # The revival branch must not turn every tool call into a
        # registration attempt for a healthy session.
        _patch_state(monkeypatch, found=True, stored_actor_id=4, ended=False)
        monkeypatch.setattr(
            register_module, "placeholder_identity_can_upgrade",
            lambda *_a, **_k: False,
        )
        monkeypatch.setattr(
            register_module, "_register_from_hook",
            lambda *_a, **_k: pytest.fail("must not register a live session"),
        )

        assert (
            register_module.ensure_registered_from_hook(object(), "{}", "s-1")
            is False
        )
