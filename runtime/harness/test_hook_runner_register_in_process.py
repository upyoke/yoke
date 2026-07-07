"""Tests for the in-process (server-side) registration branch.

``register_in_process=True`` is the remote-evaluation shape: the
checkout gating and the service-client subprocess are bypassed and the
domain registrar is called directly (field-note 12445 regression
coverage lives at the HTTP route level in
``runtime/api/test_api_hooks_evaluate_route.py``).
"""

from __future__ import annotations

import pytest

from runtime.harness import hook_runner_register as register_module


class TestRegisterInProcess:
    """register_in_process=True bypasses checkout gating + the subprocess."""

    def _sentinels(self, monkeypatch):
        monkeypatch.setattr(
            register_module, "resolve_hook_script_dir",
            lambda: pytest.fail("in-process registration must not resolve script dir"),
        )
        monkeypatch.setattr(
            register_module, "register_harness_session",
            lambda **_k: pytest.fail("in-process registration must not spawn the wrapper"),
        )

    def test_in_process_calls_domain_registrar(self, monkeypatch):
        self._sentinels(monkeypatch)
        seen: list[dict] = []
        monkeypatch.setattr(
            register_module, "_register_in_process",
            lambda sid, executor, provider, model, workspace, entrypoint,
            actor_id=None, execution_lane=None, project_id=None:
                seen.append({
                    "sid": sid, "executor": executor, "workspace": workspace,
                    "lane": execution_lane, "project_id": project_id,
                }) or "",
        )
        err, executor, _p, _m, _e = register_module._register_from_hook(
            '{"session_id": "s-srv", "cwd": "/client/checkout", '
            '"project_id": 1}', "s-srv",
            register_in_process=True, executor_hint="codex",
        )
        assert err == ""
        assert executor == "codex"
        assert seen == [{
            "sid": "s-srv", "executor": "codex",
            "workspace": "/client/checkout", "lane": None,
            "project_id": 1,
        }]

    def test_in_process_without_payload_cwd_uses_empty_workspace(self, monkeypatch):
        self._sentinels(monkeypatch)
        seen: list[str] = []
        monkeypatch.setattr(
            register_module, "_register_in_process",
            lambda sid, executor, provider, model, workspace, entrypoint,
            actor_id=None, execution_lane=None, project_id=None:
                seen.append(workspace) or "",
        )
        register_module._register_from_hook(
            '{"project_id": 1}', "s-srv", register_in_process=True,
            executor_hint="claude",
        )
        assert seen == [""]

    def test_in_process_registrar_errors_are_returned_not_raised(self, monkeypatch):
        self._sentinels(monkeypatch)
        monkeypatch.setattr(
            register_module, "_register_in_process",
            lambda *a, **k: "db unreachable",
        )
        err, *_ = register_module._register_from_hook(
            "{}", "s-srv", register_in_process=True, executor_hint="claude",
        )
        assert err == "db unreachable"

    def test_in_process_passes_verified_actor(self, monkeypatch):
        self._sentinels(monkeypatch)
        seen: list = []
        monkeypatch.setattr(
            register_module, "_register_in_process",
            lambda sid, executor, provider, model, workspace, entrypoint,
            actor_id=None, execution_lane=None, project_id=None:
                seen.append(actor_id) or "",
        )
        register_module._register_from_hook(
            '{"project_id": 1}', "s-srv", register_in_process=True,
            executor_hint="claude", actor_id=11,
        )
        assert seen == [11]

    def test_in_process_passes_payload_lane(self, monkeypatch):
        self._sentinels(monkeypatch)
        seen: list[str | None] = []
        monkeypatch.setattr(
            register_module, "_register_in_process",
            lambda sid, executor, provider, model, workspace, entrypoint,
            actor_id=None, execution_lane=None, project_id=None:
                seen.append(execution_lane) or "",
        )
        register_module._register_from_hook(
            '{"execution_lane": "DARIUS", "project_id": 1}', "s-srv",
            register_in_process=True, executor_hint="claude",
        )
        assert seen == ["DARIUS"]


def test_in_process_payload_entrypoint_preferred(monkeypatch):
    monkeypatch.setattr(
        register_module, "resolve_hook_script_dir",
        lambda: pytest.fail("in-process registration must not resolve script dir"),
    )
    monkeypatch.setattr(
        register_module, "register_harness_session",
        lambda **_k: pytest.fail("in-process registration must not spawn the wrapper"),
    )
    seen = []
    monkeypatch.setattr(
        register_module, "_register_in_process",
        lambda sid, executor, provider, model, workspace, entrypoint,
        actor_id=None, execution_lane=None, project_id=None:
            seen.append((model, entrypoint)) or "",
    )
    register_module._register_from_hook(
        '{"session_id": "s", "model": "claude-fable-5[1m]", '
        '"entrypoint": "claude-desktop", "project_id": 1}',
        "s", register_in_process=True, executor_hint="claude",
    )
    assert seen == [("claude-fable-5[1m]", "claude-desktop")]


class TestEnsureForceReregister:
    def test_force_skips_probe_and_registers(self, monkeypatch):
        monkeypatch.setattr(
            "yoke_core.domain.events_session_actor.session_actor_lookup",
            lambda *_a: pytest.fail("force path must not probe"),
        )
        calls = []
        monkeypatch.setattr(
            register_module, "_register_from_hook",
            lambda payload, sid, **kw: calls.append((sid, kw)) or ("", "c", "a", "m", None),
        )
        drove = register_module.ensure_registered_from_hook(
            object(), "{}", "s-f",
            register_in_process=True, force_reregister=True,
        )
        assert drove is True
        assert calls and calls[0][0] == "s-f"


class TestEnsureActorBackfill:
    """Field-note 12610: the heartbeat backfill can register a relayed
    session first (actor-less); a later ensure with the verified token
    actor must drive registration so the SESSION_EXISTS actor backfill
    binds it — and a row whose actor is already bound stays untouched."""

    def _patch_lookup(self, monkeypatch, stored_actor_id):
        monkeypatch.setattr(
            "yoke_core.domain.events_session_actor.session_actor_lookup",
            lambda _conn, _sid: (True, stored_actor_id),
        )

    def test_actor_less_row_with_verified_actor_drives_backfill(self, monkeypatch):
        self._patch_lookup(monkeypatch, stored_actor_id=None)
        calls: list[tuple] = []
        monkeypatch.setattr(
            register_module, "_register_from_hook",
            lambda payload, sid, transcript_path="", record_anchor=True,
            executor_hint="", register_in_process=False,
            actor_id=None, project_id=None: calls.append((sid, actor_id, project_id))
            or ("", "claude", "anthropic", "m", None),
        )
        drove = register_module.ensure_registered_from_hook(
            object(), "{}", "s-backfill",
            register_in_process=True, actor_id=4, project_id=1,
        )
        assert drove is True
        assert calls == [("s-backfill", 4, 1)]

    def test_actor_bound_row_skips_even_with_verified_actor(self, monkeypatch):
        self._patch_lookup(monkeypatch, stored_actor_id=9)
        monkeypatch.setattr(
            register_module, "_register_from_hook",
            lambda *a, **k: pytest.fail("bound actor must not re-register"),
        )
        assert (
            register_module.ensure_registered_from_hook(
                object(), "{}", "s-bound",
                register_in_process=True, actor_id=4,
            )
            is False
        )
