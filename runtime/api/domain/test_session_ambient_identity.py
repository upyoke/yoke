"""Unit tests for the canonical ambient session-identity chain.

Covers the resolution order pin: the owning harness family scopes the
chain, then that family's env variables, then the process-anchor
ancestry walk, then ``None``. The ancestry step is exercised against a
tmp machine home so no test reads the real registry, and the owning
family is always pinned so no test reads the machine's process tree.
"""

from __future__ import annotations

import os

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
    # No harness ancestor by default: the family-blind chain, and never
    # the process tree of whichever harness happens to run the suite.
    monkeypatch.setattr(ambient, "nearest_harness_family", lambda *_a, **_k: None)
    return home


@pytest.fixture()
def owning_family(monkeypatch):
    """Pin the harness family the process tree would otherwise name."""
    def _pin(family):
        monkeypatch.setattr(
            ambient, "nearest_harness_family", lambda *_a, **_k: family,
        )

    return _pin


class TestEnvChain:
    def test_canonical_constant(self):
        assert ambient.AMBIENT_ENV_VARS == (
            "YOKE_SESSION_ID",
            "CLAUDE_CODE_SESSION_ID",
            "CODEX_SESSION_ID",
            "CODEX_THREAD_ID",
        )

    def test_yoke_wins(self):
        env = {
            "YOKE_SESSION_ID": "yok-1",
            "CLAUDE_CODE_SESSION_ID": "claude-1",
            "CODEX_THREAD_ID": "codex-1",
        }
        assert ambient.resolve_env_session_id(env) == "yok-1"

    def test_falls_back_to_claude_then_codex(self):
        assert (
            ambient.resolve_env_session_id({"CLAUDE_CODE_SESSION_ID": "c-1"})
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
            "CLAUDE_CODE_SESSION_ID": "env:claude-code",
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


class TestNestedHarnessSpawn:
    """A harness started inside another harness inherits its variable.

    Live-reproduced on both: a ``codex exec`` run and a Cursor agent run,
    each launched from a Claude session's shell, resolved to that Claude
    session and would have acted with its authority while their own
    registrations sat unused.
    """

    def test_codex_child_resolves_to_its_own_session(
        self, machine_home, owning_family,
    ):
        owning_family("codex")
        assert ambient.resolve_ambient_session_id({
            "CLAUDE_CODE_SESSION_ID": "claude-parent",
            "CODEX_SESSION_ID": "codex-child",
        }) == "codex-child"

    def test_cursor_child_resolves_through_its_conversation_map(
        self, machine_home, owning_family,
    ):
        record_conversation_session(
            "conv-child",
            "cursor-child",
            machine_home / CURSOR_SESSION_MAP_DIR_NAME,
        )
        owning_family("cursor")
        assert ambient.resolve_ambient_session_id({
            "CLAUDE_CODE_SESSION_ID": "claude-parent",
            "CURSOR_CONVERSATION_ID": "conv-child",
        }) == "cursor-child"

    def test_a_family_that_stamped_nothing_reports_no_identity(
        self, machine_home, owning_family,
    ):
        """Refusing beats answering with the launching session's variable."""
        owning_family("codex")
        assert ambient.resolve_ambient_session_id({
            "CLAUDE_CODE_SESSION_ID": "claude-parent",
        }) is None

    def test_claude_child_of_a_codex_session_resolves_to_itself(
        self, machine_home, owning_family,
    ):
        owning_family("claude-code")
        assert ambient.resolve_ambient_session_id({
            "CODEX_SESSION_ID": "codex-parent",
            "CLAUDE_CODE_SESSION_ID": "claude-child",
        }) == "claude-child"

    def test_the_explicit_stamp_outranks_the_owning_family(
        self, machine_home, owning_family,
    ):
        owning_family("codex")
        assert ambient.resolve_ambient_session_id({
            "YOKE_SESSION_ID": "pinned",
            "CLAUDE_CODE_SESSION_ID": "claude-parent",
        }) == "pinned"

    def test_the_owning_family_reaches_the_cli_chokepoint(
        self, machine_home, owning_family,
    ):
        from yoke_core.api.service_client_shared_session_resolver import (
            _resolve_session_id,
        )

        owning_family("codex")
        monkey_env = {"CLAUDE_CODE_SESSION_ID": "claude-parent"}
        for name, value in monkey_env.items():
            os.environ[name] = value
        try:
            assert _resolve_session_id(None) is None
        finally:
            for name in monkey_env:
                os.environ.pop(name, None)


class TestOwningFamilyDiagnostics:
    """The denial names the family, the reason an inherited value lost."""

    def test_channels_report_the_owning_family(
        self, machine_home, owning_family,
    ):
        owning_family("codex")
        channels = {
            row["channel"]: row["raw"]
            for row in ambient.consult_identity_channels()
        }
        assert channels["process_family"] == "codex"

    def test_denial_text_names_the_owning_family(
        self, machine_home, owning_family,
    ):
        owning_family("codex")
        assert "process_family=codex" in ambient.format_actor_session_missing(
            "items.create",
        )


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
