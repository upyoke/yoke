"""Free-path allowlist regression coverage for ``lint_session_cwd_validate``.

Covers the S4 expansion: ``/dev/null`` / ``/dev/stderr`` /
``/dev/stdout``, the ``~/.claude/projects/`` harness-internal
artifact tree, and the ``~/.codex/sessions/`` plus
``~/.codex/archived_sessions/`` Codex transcript trees (added so the
cross-harness transcript audit can walk Codex rollouts from any
worktree). Also covers watcher-minted capture paths under the live
machine scratch root's ``watcher-captures/`` subtree. Each free-path
case must allow regardless of the session's claim set; ``/etc/passwd``
and similar real repo-tree paths must still deny when the session has
an active claim.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.lint_session_cwd_validate import (
    FREE_PATH_PREFIXES,
    is_yoke_watcher_capture_path,
    validate_targets,
)
from yoke_core.domain.project_scratch_dir import (
    dispatch_inputs_dir,
    mint_watcher_capture_pair,
)


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def session_with_claim(conn, tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees" / "YOK-100").mkdir(parents=True)
    register_machine_checkout(tmp_path / "machine-config", repo_path, 1)
    seed_item(conn, item_id=100, branch="YOK-100", repo_path=repo_path)
    seed_item_claim(conn, "s1", item_id=100)
    return "s1"


class TestFreePathPrefixesContainExpectedRoots:
    """Static check: the expansion landed and the literal forms are present."""

    def test_dev_family_in_free_paths(self) -> None:
        assert "/dev" in FREE_PATH_PREFIXES

    def test_harness_internal_literal_form_in_free_paths(self) -> None:
        assert "~/.claude/projects" in FREE_PATH_PREFIXES

    def test_harness_internal_expanded_form_in_free_paths(self) -> None:
        home = os.path.expanduser("~")
        expected = os.path.join(home, ".claude", "projects")
        assert expected in FREE_PATH_PREFIXES

    def test_codex_sessions_literal_form_in_free_paths(self) -> None:
        assert "~/.codex/sessions" in FREE_PATH_PREFIXES

    def test_codex_sessions_expanded_form_in_free_paths(self) -> None:
        home = os.path.expanduser("~")
        expected = os.path.join(home, ".codex", "sessions")
        assert expected in FREE_PATH_PREFIXES

    def test_codex_archived_sessions_literal_form_in_free_paths(self) -> None:
        assert "~/.codex/archived_sessions" in FREE_PATH_PREFIXES

    def test_codex_archived_sessions_expanded_form_in_free_paths(self) -> None:
        home = os.path.expanduser("~")
        expected = os.path.join(home, ".codex", "archived_sessions")
        assert expected in FREE_PATH_PREFIXES


class TestDevFamilyAllowed:
    """``/dev/null`` and friends bypass claim authority."""

    @pytest.mark.parametrize("target", [
        "/dev/null",
        "/dev/stderr",
        "/dev/stdout",
        "/dev/tty",
    ])
    def test_dev_targets_allowed(
        self, conn, session_with_claim, target
    ) -> None:
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow, (
            f"expected {target} to be allowed via /dev free-path prefix"
        )


class TestHarnessInternalAllowed:
    """``~/.claude/projects/<session>/...`` lands in tool-results / persisted-output."""

    def test_tool_results_literal_tilde_allowed(
        self, conn, session_with_claim
    ) -> None:
        target = "~/.claude/projects/-Users-x-yoke/sess/tool-results/file.txt"
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow

    def test_tool_results_expanded_allowed(
        self, conn, session_with_claim
    ) -> None:
        home = os.path.expanduser("~")
        target = os.path.join(
            home,
            ".claude",
            "projects",
            "-Users-x-yoke",
            "sess",
            "tool-results",
            "file.txt",
        )
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow

    def test_persisted_output_allowed(
        self, conn, session_with_claim
    ) -> None:
        home = os.path.expanduser("~")
        target = os.path.join(
            home,
            ".claude",
            "projects",
            "-Users-x-yoke",
            "sess",
            "persisted-output",
            "capture.txt",
        )
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow


class TestCodexHarnessInternalAllowed:
    """``~/.codex/sessions/...`` and ``~/.codex/archived_sessions/...`` are symmetric to the Claude tree."""

    def test_codex_sessions_literal_tilde_allowed(
        self, conn, session_with_claim
    ) -> None:
        target = "~/.codex/sessions/2026/04/03/rollout-019d54b0.jsonl"
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow

    def test_codex_sessions_expanded_allowed(
        self, conn, session_with_claim
    ) -> None:
        home = os.path.expanduser("~")
        target = os.path.join(
            home,
            ".codex",
            "sessions",
            "2026",
            "04",
            "03",
            "rollout-019d54b0.jsonl",
        )
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow

    def test_codex_archived_sessions_literal_tilde_allowed(
        self, conn, session_with_claim
    ) -> None:
        target = "~/.codex/archived_sessions/old-rollout.jsonl"
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow

    def test_codex_archived_sessions_expanded_allowed(
        self, conn, session_with_claim
    ) -> None:
        home = os.path.expanduser("~")
        target = os.path.join(
            home,
            ".codex",
            "archived_sessions",
            "old-rollout.jsonl",
        )
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow


class TestWatcherMintedCapturePairAllowed:
    """Printed ``--print-streaming-pair`` paths must pass write authority."""

    def test_minted_pair_targets_allowed(
        self, conn, session_with_claim, monkeypatch, tmp_path
    ) -> None:
        # Scratch must sit outside /tmp and /var/folders so the allowlist
        # under test is the watcher-captures rule, not OS temp free-paths.
        scratch = Path.home() / ".yoke" / "test-scratch-watcher-authority"
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir(parents=True)
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(scratch))
        try:
            raw, progress = mint_watcher_capture_pair("pytest")
            assert str(raw).startswith(str(scratch.resolve()))
            assert is_yoke_watcher_capture_path(str(raw))
            for target in (str(raw), str(progress)):
                verdict = validate_targets(
                    conn,
                    session_id=session_with_claim,
                    targets=[target],
                )
                assert verdict.allow, (
                    f"expected minted watcher capture {target} to pass "
                    f"write-authority via watcher-captures free-path"
                )
            dispatch_target = str(
                dispatch_inputs_dir(
                    item_id=100,
                    session_id="s1",
                    attempt=1,
                    create=False,
                )
                / "prompt.md"
            )
            assert not is_yoke_watcher_capture_path(dispatch_target)
            denied = validate_targets(
                conn,
                session_id=session_with_claim,
                targets=[dispatch_target],
            )
            assert not denied.allow
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


class TestNegativeRegression:
    """Real repo-tree paths outside the session's claim still deny."""

    def test_etc_passwd_still_denied(
        self, conn, session_with_claim
    ) -> None:
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=["/etc/passwd"],
        )
        assert not verdict.allow
        assert "/etc/passwd" in verdict.offending_target
