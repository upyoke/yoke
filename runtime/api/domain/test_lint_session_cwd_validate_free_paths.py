"""Free-path allowlist regression coverage for ``lint_session_cwd_validate``.

Covers the S4 expansion: ``/dev/null`` / ``/dev/stderr`` /
``/dev/stdout``, the ``~/.claude/projects/`` harness-internal
artifact tree, and the ``~/.codex/sessions/`` plus
``~/.codex/archived_sessions/`` Codex transcript trees (added so the
cross-harness transcript audit can walk Codex rollouts from any
worktree). Each free-path case must allow regardless of the session's
claim set; ``/etc/passwd`` and similar real repo-tree paths must still
deny when the session has an active claim.
"""

from __future__ import annotations

import os

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.lint_session_cwd_validate import (
    FREE_PATH_PREFIXES,
    validate_targets,
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
    seed_item(conn, item_id=100, branch="YOK-100")
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
