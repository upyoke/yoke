"""Unit tests for the canonical ambient session-identity chain.

Covers the resolution order pin: env chain first (fast path), then the
process-anchor ancestry walk, then ``None``. The ancestry step is
exercised against a tmp machine home so no test reads the real registry.
"""

from __future__ import annotations

import pytest

from yoke_contracts import session_identity
from yoke_contracts.process_ancestry import ProcessAnchor

from yoke_core.domain import session_ambient_identity as ambient
from yoke_core.domain import session_process_anchors as anchors


@pytest.fixture()
def machine_home(tmp_path, monkeypatch):
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    for name in ambient.AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return home


class TestEnvChain:
    def test_canonical_constant(self):
        assert ambient.AMBIENT_ENV_VARS == (
            "YOKE_SESSION_ID",
            "CLAUDE_SESSION_ID",
            "CODEX_THREAD_ID",
        )

    def test_yoke_wins(self):
        env = {
            "YOKE_SESSION_ID": "yok-1",
            "CLAUDE_SESSION_ID": "claude-1",
            "CODEX_THREAD_ID": "codex-1",
        }
        assert ambient.resolve_env_session_id(env) == "yok-1"

    def test_falls_back_to_claude_then_codex(self):
        assert (
            ambient.resolve_env_session_id({"CLAUDE_SESSION_ID": "c-1"})
            == "c-1"
        )
        assert (
            ambient.resolve_env_session_id({"CODEX_THREAD_ID": "x-1"})
            == "x-1"
        )

    def test_empty_env_yields_none(self):
        assert ambient.resolve_env_session_id({}) is None


class TestAmbientChain:
    def test_env_fast_path_skips_ancestry(self, machine_home, monkeypatch):
        def _boom(*_a, **_k):
            raise AssertionError("ancestry must not run when env resolves")

        monkeypatch.setattr(anchors, "resolve_session_from_ancestry", _boom)
        assert (
            ambient.resolve_ambient_session_id({"YOKE_SESSION_ID": "s-env"})
            == "s-env"
        )

    def test_ancestry_resolves_when_env_empty(self, machine_home, monkeypatch):
        anchors.record_session_anchor(
            "sess-anchored",
            anchor=ProcessAnchor(
                pid=4242, start_time="start-x", process_name="claude",
            ),
        )
        monkeypatch.setattr(
            session_identity, "ancestor_pids",
            lambda _pid=None, parents=None: [4242],
        )
        monkeypatch.setattr(
            session_identity, "process_start_time",
            lambda _pid: "start-x",
        )
        assert ambient.resolve_ambient_session_id({}) == "sess-anchored"

    def test_none_when_nothing_resolves(self, machine_home):
        assert ambient.resolve_ambient_session_id({}) is None


class TestCliChokepointDelegation:
    """``_resolve_session_id`` rides the same chain: explicit → ambient."""

    def test_explicit_override_wins(self, machine_home):
        from yoke_core.api.service_client_shared_session_resolver import (
            _resolve_session_id,
        )

        assert _resolve_session_id("explicit-x") == "explicit-x"

    def test_ancestry_reaches_the_cli_chokepoint(
        self, machine_home, monkeypatch
    ):
        from yoke_core.api import service_client_shared_session_resolver as scr

        anchors.record_session_anchor(
            "sess-cli",
            anchor=ProcessAnchor(
                pid=777, start_time="s-777", process_name="claude",
            ),
        )
        monkeypatch.setattr(
            session_identity, "ancestor_pids",
            lambda _pid=None, parents=None: [777],
        )
        monkeypatch.setattr(
            session_identity, "process_start_time",
            lambda _pid: "s-777",
        )
        assert scr._resolve_session_id(None) == "sess-cli"
        assert scr.current_session_id() == "sess-cli"

    def test_none_everywhere_yields_none(self, machine_home):
        from yoke_core.api.service_client_shared_session_resolver import (
            _resolve_session_id,
        )

        assert _resolve_session_id(None) is None
