"""Unit tests for the canonical ambient session-identity chain.

Covers the resolution order pin: env chain first (fast path), then the
process-anchor ancestry walk, then ``None``. The ancestry step is
exercised against a tmp machine home so no test reads the real registry.
"""

from __future__ import annotations

import pytest

from yoke_contracts import session_identity
from yoke_contracts.cursor_session_map import (
    CURSOR_SESSION_MAP_DIR_NAME,
    record_conversation_session,
)
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
            "CODEX_SESSION_ID",
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
            ambient.resolve_env_session_id({"CODEX_SESSION_ID": "p-1"})
            == "p-1"
        )
        assert (
            ambient.resolve_env_session_id({"CODEX_THREAD_ID": "x-1"})
            == "x-1"
        )

    def test_every_chain_variable_resolves_alone(self):
        """No variable in the chain is unreachable."""
        for name in ambient.AMBIENT_ENV_VARS:
            assert (
                ambient.resolve_env_session_id({name: f"sid-{name}"})
                == f"sid-{name}"
            )

    def test_empty_env_yields_none(self):
        assert ambient.resolve_env_session_id({}) is None


class TestCodexParentAndChild:
    """A Codex subagent shell must resolve to the session Yoke registered.

    Codex sets ``CODEX_SESSION_ID`` to the parent thread in both the
    parent and the subagent process, and ``CODEX_THREAD_ID`` to whichever
    thread is running. Resolving the child names a thread with no
    ``harness_sessions`` row, which is what left subagent calls
    unclaimed.
    """

    def test_subagent_env_resolves_to_the_parent(self):
        env = {
            "CODEX_SESSION_ID": "codex-parent",
            "CODEX_THREAD_ID": "codex-child",
        }
        assert ambient.resolve_env_session_id(env) == "codex-parent"

    def test_parent_env_resolves_unchanged(self):
        env = {
            "CODEX_SESSION_ID": "codex-parent",
            "CODEX_THREAD_ID": "codex-parent",
        }
        assert ambient.resolve_env_session_id(env) == "codex-parent"

    def test_explicit_pin_still_outranks_both(self):
        env = {
            "YOKE_SESSION_ID": "pinned",
            "CODEX_SESSION_ID": "codex-parent",
            "CODEX_THREAD_ID": "codex-child",
        }
        assert ambient.resolve_env_session_id(env) == "pinned"


class TestPublicChannelLabels:
    """Diagnostic labels track the chain instead of its old positions."""

    def test_every_chain_variable_has_its_own_label(self):
        labels = {
            name: ambient._public_channel(f"env:{name}")
            for name in ambient.AMBIENT_ENV_VARS
        }
        assert labels == {
            "YOKE_SESSION_ID": "env:session",
            "CLAUDE_SESSION_ID": "env:claude",
            "CODEX_SESSION_ID": "env:codex",
            "CODEX_THREAD_ID": "env:codex-thread",
        }

    def test_unknown_variable_and_non_env_channels(self):
        assert ambient._public_channel("env:SOMETHING_ELSE") == "env:other"
        assert ambient._public_channel("process_anchor") == "process_anchor"

    def test_labels_never_name_a_chain_variable(self):
        """The label exists so a denial never teaches self-bootstrap."""
        for name in ambient.AMBIENT_ENV_VARS:
            assert name not in ambient._public_channel(f"env:{name}")


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
            session_identity, "anchor_candidate_pids",
            lambda _pid=None, parents=None, name_of=None: [4242],
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
            session_identity, "anchor_candidate_pids",
            lambda _pid=None, parents=None, name_of=None: [777],
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


class TestHookPayloadFold:
    def test_mapped_conversation_resolves_to_session(self, machine_home):
        record_conversation_session(
            "conv-1", "sid-mapped", machine_home / CURSOR_SESSION_MAP_DIR_NAME,
        )
        assert ambient.session_id_from_hook_payload({
            "session_id": "conv-1",
            "conversation_id": "conv-1",
        }) == "sid-mapped"

    def test_unmapped_conversation_is_empty(self, machine_home):
        assert ambient.session_id_from_hook_payload({
            "session_id": "conv-unknown",
            "conversation_id": "conv-unknown",
        }) == ""

    def test_real_session_id_is_unchanged(self, machine_home):
        assert ambient.session_id_from_hook_payload({
            "session_id": "sid-claude",
        }) == "sid-claude"
