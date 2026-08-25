"""Unit tests for harness-family identity resolution.

Covers the process-tree classification that decides which harness a
process belongs to, the per-family environment vocabulary, and the
nested-spawn regressions those two exist for: a harness started from
inside another harness's shell inherits that harness's session variable
and must not answer with it.
"""

from __future__ import annotations

import pytest

from yoke_contracts import harness_family_identity as families
from yoke_contracts import session_identity
from yoke_contracts.cursor_session_map import record_conversation_session


CLAUDE_PARENT = "claude-parent-session"
CODEX_CHILD = "codex-child-session"
CURSOR_CHILD = "cursor-child-session"


@pytest.fixture()
def identity_dirs(tmp_path):
    """A machine home's two identity registries, both empty."""
    anchors = tmp_path / "session-anchors"
    cursor_map = tmp_path / "cursor-session-map"
    anchors.mkdir()
    cursor_map.mkdir()
    return anchors, cursor_map


def _tree(*names: str):
    """A process chain (this process first) named by ``names``."""
    pids = [100 + index for index in range(len(names))]
    parents = {pid: pids[index + 1] for index, pid in enumerate(pids[:-1])}
    parents[pids[-1]] = 1
    return pids[0], parents, dict(zip(pids, names)).get


class TestHarnessFamilyOfProcessName:
    def test_per_session_binaries(self):
        assert families.harness_family_of_process_name("claude") == "claude-code"
        assert (
            families.harness_family_of_process_name("claude-code")
            == "claude-code"
        )

    def test_multiplexed_hosts_still_name_their_family(self):
        """A shared host cannot anchor a session but does name a harness."""
        assert families.harness_family_of_process_name("codex") == "codex"
        assert (
            families.harness_family_of_process_name("codex-code-mode-host")
            == "codex"
        )
        assert families.harness_family_of_process_name("cursor") == "cursor"
        assert (
            families.harness_family_of_process_name("cursor-agent") == "cursor"
        )

    def test_pooled_claude_hosts_announce_their_role_in_the_title(self):
        for name in ("claude bg-pty-host", "claude bg-spare"):
            assert (
                families.harness_family_of_process_name(name) == "claude-code"
            )

    def test_full_executable_path_is_basenamed(self):
        assert (
            families.harness_family_of_process_name(
                "/Applications/Codex.app/Contents/MacOS/codex"
            )
            == "codex"
        )

    def test_non_harness_processes_and_empty_input(self):
        for name in ("python3", "bash", "Claude Helper", "", None):
            assert families.harness_family_of_process_name(name) is None


class TestNearestHarnessFamily:
    def test_nested_codex_names_codex_not_the_launching_claude(self):
        pid, parents, name_of = _tree("bash", "codex", "claude")
        assert (
            families.nearest_harness_family(
                pid, parents=parents, name_of=name_of,
            )
            == "codex"
        )

    def test_nested_claude_names_claude_not_the_launching_codex(self):
        pid, parents, name_of = _tree("bash", "claude", "codex")
        assert (
            families.nearest_harness_family(
                pid, parents=parents, name_of=name_of,
            )
            == "claude-code"
        )

    def test_walk_passes_through_a_multiplexed_host(self):
        """Unlike the anchor walk: the question is ownership, not anchoring."""
        pid, parents, name_of = _tree("bash", "cursor-agent")
        assert (
            families.nearest_harness_family(
                pid, parents=parents, name_of=name_of,
            )
            == "cursor"
        )

    def test_no_harness_ancestor_yields_none(self):
        pid, parents, name_of = _tree("bash", "zsh", "login")
        assert (
            families.nearest_harness_family(
                pid, parents=parents, name_of=name_of,
            )
            is None
        )

    def test_injected_tree_without_names_classifies_nothing(self):
        """Live names against a synthetic tree would decide by coincidence."""
        assert families.nearest_harness_family(100, parents={100: 1}) is None

    def test_never_raises(self, monkeypatch):
        def _boom(*_args, **_kwargs):
            raise RuntimeError("process table unavailable")

        monkeypatch.setattr(families, "process_table", _boom)
        monkeypatch.setattr(families, "_nearest_family_by_pid", {})
        assert families.nearest_harness_family() is None


class TestFamilyEnvSessionId:
    def test_claude_reads_its_own_variable(self):
        assert (
            families.family_env_session_id(
                "claude-code", {"CLAUDE_CODE_SESSION_ID": CLAUDE_PARENT},
            )
            == CLAUDE_PARENT
        )

    def test_codex_reads_parent_before_child(self):
        assert (
            families.family_env_session_id(
                "codex",
                {
                    "CODEX_SESSION_ID": "codex-parent",
                    "CODEX_THREAD_ID": "codex-thread",
                },
            )
            == "codex-parent"
        )

    def test_cursor_stamps_no_session_variable(self):
        assert (
            families.family_env_session_id(
                "cursor", {"CURSOR_CONVERSATION_ID": "conv-1"},
            )
            is None
        )

    def test_a_family_reads_only_its_own_variables(self):
        assert (
            families.family_env_session_id(
                "codex", {"CLAUDE_CODE_SESSION_ID": CLAUDE_PARENT},
            )
            is None
        )

    def test_unknown_family_and_empty_env(self):
        assert families.family_env_session_id(None, {}) is None
        assert families.family_env_session_id("emacs", {}) is None


class TestAmbientEnvVocabulary:
    def test_chain_order_is_pinned(self):
        assert families.AMBIENT_ENV_VARS == (
            "YOKE_SESSION_ID",
            "CLAUDE_CODE_SESSION_ID",
            "CODEX_SESSION_ID",
            "CODEX_THREAD_ID",
        )

    def test_session_identity_re_exports_the_same_tuple(self):
        assert session_identity.AMBIENT_ENV_VARS is families.AMBIENT_ENV_VARS

    def test_every_session_id_family_is_in_the_chain(self):
        for family in families.SESSION_ID_ENV_FAMILIES:
            for name in families.HARNESS_FAMILY_ENV_VARS[family]:
                assert name in families.AMBIENT_ENV_VARS


class TestAmbientChainIsFamilyScoped:
    """The nested-spawn regressions, live-reproduced on Codex and Cursor."""

    def _resolve(self, monkeypatch, identity_dirs, family, env):
        anchors, cursor_map = identity_dirs
        monkeypatch.setattr(
            session_identity, "nearest_harness_family",
            lambda *_a, **_k: family,
        )
        return session_identity.resolve_ambient_session_id(
            anchors, env, cursor_map_dir=cursor_map,
        )

    def test_nested_codex_resolves_to_its_own_session(
        self, monkeypatch, identity_dirs,
    ):
        assert self._resolve(
            monkeypatch, identity_dirs, "codex",
            {
                "CLAUDE_CODE_SESSION_ID": CLAUDE_PARENT,
                "CODEX_SESSION_ID": CODEX_CHILD,
            },
        ) == CODEX_CHILD

    def test_nested_cursor_resolves_through_its_conversation_map(
        self, monkeypatch, identity_dirs,
    ):
        _anchors, cursor_map = identity_dirs
        record_conversation_session("conv-child", CURSOR_CHILD, cursor_map)
        assert self._resolve(
            monkeypatch, identity_dirs, "cursor",
            {
                "CLAUDE_CODE_SESSION_ID": CLAUDE_PARENT,
                "CURSOR_CONVERSATION_ID": "conv-child",
            },
        ) == CURSOR_CHILD

    def test_a_family_that_stamped_nothing_reports_no_identity(
        self, monkeypatch, identity_dirs,
    ):
        """Refusing beats answering with the launching session's variable."""
        assert self._resolve(
            monkeypatch, identity_dirs, "codex",
            {"CLAUDE_CODE_SESSION_ID": CLAUDE_PARENT},
        ) is None

    def test_nested_claude_resolves_to_its_own_session(
        self, monkeypatch, identity_dirs,
    ):
        assert self._resolve(
            monkeypatch, identity_dirs, "claude-code",
            {
                "CODEX_SESSION_ID": "codex-parent",
                "CLAUDE_CODE_SESSION_ID": "claude-child",
            },
        ) == "claude-child"

    def test_an_inherited_conversation_id_never_answers_for_another_family(
        self, monkeypatch, identity_dirs,
    ):
        _anchors, cursor_map = identity_dirs
        record_conversation_session("conv-outer", CURSOR_CHILD, cursor_map)
        assert self._resolve(
            monkeypatch, identity_dirs, "codex",
            {"CURSOR_CONVERSATION_ID": "conv-outer"},
        ) is None

    def test_the_explicit_stamp_outranks_the_owning_family(
        self, monkeypatch, identity_dirs,
    ):
        assert self._resolve(
            monkeypatch, identity_dirs, "codex",
            {
                "YOKE_SESSION_ID": "pinned",
                "CLAUDE_CODE_SESSION_ID": CLAUDE_PARENT,
            },
        ) == "pinned"

    def test_without_a_harness_ancestor_the_chain_is_family_blind(
        self, monkeypatch, identity_dirs,
    ):
        """CI, an operator terminal, a reparented process: nothing inherited."""
        assert self._resolve(
            monkeypatch, identity_dirs, None,
            {"CLAUDE_CODE_SESSION_ID": CLAUDE_PARENT},
        ) == CLAUDE_PARENT
