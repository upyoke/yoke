"""Tests for :mod:`lint_session_cwd` under the claim-based authority.

The session-cwd policy reads ``work_claims`` directly (via
:func:`session_claimed_worktrees.claimed_worktrees`) and validates each
tool-call target against the session's claimed worktrees, the control
plane of the claimed projects, or the free-path allowlist. There is
no scope envelope; sessions with no claims pass unconditionally.

The ``conn`` fixture is a disposable schema-loaded Postgres database;
``pg_testdb.test_database`` repoints the ambient DSN at it, so the
lint's self-resolved connection lands in the same database as the
fixture's seeds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_session_cwd
from yoke_core.domain.lint_session_cwd_validate import validate_targets
from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_command_targets,
)
from runtime.harness.hook_runner.types import HookContext, Next, Outcome


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _register_checkout(repo_path, project_id=1):
    register_machine_checkout(
        Path(repo_path).parent / "machine-config",
        Path(repo_path),
        project_id,
    )


class TestNoSession:
    def test_payload_without_session_id_allows(self, conn):
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "cwd": "/some/random/path",
        })
        assert verdict.allow is True


class TestNoClaims:
    def test_session_without_claims_allows(self, conn):
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-noclaims",
            "cwd": "/some/random/path",
        })
        assert verdict.allow is True


class TestClaimedWorktreeAuthorized:
    def test_target_inside_claimed_worktree_allows(self, conn, repo):
        _register_checkout(repo)
        seed_item(conn, item_id=1691, branch="YOK-1691")
        seed_item_claim(conn, "sid-1", item_id=1691)
        wt = repo / ".worktrees" / "YOK-1691"
        wt.mkdir(parents=True)
        target = wt / "src/file.py"
        target.parent.mkdir(parents=True)
        target.write_text("# stub")
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"file_path": str(target)},
        })
        assert verdict.allow is True
        assert len(verdict.claims) == 1

    def test_control_plane_target_allows(self, conn, repo):
        _register_checkout(repo)
        seed_item(conn, item_id=1691, branch="YOK-1691")
        seed_item_claim(conn, "sid-1", item_id=1691)
        (repo / ".worktrees" / "YOK-1691").mkdir(parents=True)
        target = repo / "docs/README.md"
        target.parent.mkdir(parents=True)
        target.write_text("# stub")
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"file_path": str(target)},
        })
        assert verdict.allow is True

    def test_free_path_target_allows(self, conn, repo):
        _register_checkout(repo)
        seed_item(conn, item_id=1691, branch="YOK-1691")
        seed_item_claim(conn, "sid-1", item_id=1691)
        (repo / ".worktrees" / "YOK-1691").mkdir(parents=True)
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"file_path": "/tmp/yoke-cmd.txt"},
        })
        assert verdict.allow is True


class TestUnauthorizedTarget:
    def test_target_outside_authority_denies(self, conn, repo):
        _register_checkout(repo)
        seed_item(conn, item_id=1691, branch="YOK-1691")
        seed_item_claim(conn, "sid-1", item_id=1691)
        (repo / ".worktrees" / "YOK-1691").mkdir(parents=True)
        # A target inside another item's worktree is not authorised.
        # Use a synthetic path so the free-path allowlist (which covers
        # /var/folders on macOS, where pytest tmp_path lives) does not
        # authorise it.
        target = "/opt/other-repo/.worktrees/YOK-OTHER/file.py"
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"file_path": target},
        })
        assert verdict.allow is False
        assert verdict.offending_target.endswith("YOK-OTHER/file.py")
        assert "BLOCKED" in verdict.reason
        assert "YOK-1691" in verdict.reason


class TestBashTargetExtraction:
    def test_git_c_target_under_claimed_worktree_allows(self, conn, repo):
        _register_checkout(repo)
        seed_item(conn, item_id=1691, branch="YOK-1691")
        seed_item_claim(conn, "sid-1", item_id=1691)
        wt = repo / ".worktrees" / "YOK-1691"
        wt.mkdir(parents=True)
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"command": f"git -C {wt} status"},
        })
        assert verdict.allow is True

    def test_bash_with_no_target_falls_back_to_cwd(self, conn, repo):
        _register_checkout(repo)
        seed_item(conn, item_id=1691, branch="YOK-1691")
        seed_item_claim(conn, "sid-1", item_id=1691)
        (repo / ".worktrees" / "YOK-1691").mkdir(parents=True)
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": str(repo),  # cwd is the repo root (control plane)
            "tool_input": {"command": "ls"},
        })
        assert verdict.allow is True

    def test_bash_cwd_outside_authority_denies(self, conn, repo):
        _register_checkout(repo)
        seed_item(conn, item_id=1691, branch="YOK-1691")
        seed_item_claim(conn, "sid-1", item_id=1691)
        (repo / ".worktrees" / "YOK-1691").mkdir(parents=True)
        # Use a synthetic non-tmp path so the free-path allowlist (which
        # covers /var/folders on macOS) does not authorise it. The
        # command must not match the read-only signature classifier
        # (``ls`` / ``cat`` / etc. all classify as read-only and are
        # allowed through on the cwd-fallback branch).
        outside = "/opt/elsewhere"
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": outside,
            "tool_input": {"command": "touch newfile"},
        })
        assert verdict.allow is False

    def test_all_absolute_positional_targets_are_checked(self, conn, repo):
        _register_checkout(repo)
        seed_item(conn, item_id=1691, branch="YOK-1691")
        seed_item_claim(conn, "sid-1", item_id=1691)
        wt = repo / ".worktrees" / "YOK-1691"
        wt.mkdir(parents=True)
        claimed_file = wt / "source.py"
        claimed_file.write_text("# stub")

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": str(repo),
            "tool_input": {
                "command": f"cp {claimed_file} /opt/elsewhere/out.py",
            },
        })

        assert verdict.allow is False
        assert verdict.offending_target == "/opt/elsewhere/out.py"

    def test_env_assignment_with_path_does_not_become_command_target(self):
        targets = extract_command_targets(
            "PYTHONPATH=/opt/shared /usr/bin/python3 "
            "/repo/control.py /opt/elsewhere/out.txt"
        )
        assert targets == ["/repo/control.py", "/opt/elsewhere/out.txt"]


class TestEvaluateTypedEntrypoint:
    def test_allow_returns_noop(self, conn):
        record = HookContext(
            event_name="PreToolUse", executor_family="claude",
            executor_surface="claude",
            payload={"session_id": "sid-noclaims", "tool_name": "Bash"},
            tool_name="Bash", cwd="/tmp",
            session_id="sid-noclaims",
        )
        decision = lint_session_cwd.evaluate(record)
        assert decision.outcome is Outcome.NOOP
        assert decision.next is Next.CONTINUE

    def test_deny_returns_deny_with_envelope(self, conn, repo):
        _register_checkout(repo)
        seed_item(conn, item_id=1691, branch="YOK-1691")
        seed_item_claim(conn, "sid-1", item_id=1691)
        (repo / ".worktrees" / "YOK-1691").mkdir(parents=True)
        target = "/opt/elsewhere/file.py"
        record = HookContext(
            event_name="PreToolUse", executor_family="claude",
            executor_surface="claude",
            payload={
                "session_id": "sid-1",
                "tool_input": {"file_path": target},
            },
            tool_name="Edit", cwd=str(repo),
            session_id="sid-1",
        )
        decision = lint_session_cwd.evaluate(record)
        assert decision.outcome is Outcome.DENY
        assert decision.block is True
        assert "BLOCKED" in (decision.message or "")

    def test_unknown_event_collapses_to_noop(self, conn):
        record = HookContext(
            event_name="SomeOtherEvent", executor_family="claude",
            executor_surface="claude", payload={},
        )
        decision = lint_session_cwd.evaluate(record)
        assert decision.outcome is Outcome.NOOP


class TestValidatorDirect:
    """Direct tests for :func:`validate_targets` — module-level smoke."""

    def test_no_session_allows(self, conn):
        verdict = validate_targets(
            conn, session_id="", targets=("/anywhere",),
        )
        assert verdict.allow is True

    def test_no_claims_allows(self, conn):
        verdict = validate_targets(
            conn, session_id="sid-empty", targets=("/anywhere",),
        )
        assert verdict.allow is True

    def test_repo_root_derived_from_worktree_path(self, conn, repo):
        _register_checkout(repo)
        seed_item(conn, item_id=1691, branch="YOK-1691")
        seed_item_claim(conn, "sid-1", item_id=1691)
        (repo / ".worktrees" / "YOK-1691").mkdir(parents=True)
        target = repo / "data" / "config.json"
        target.parent.mkdir(parents=True)
        target.write_text("{}")
        verdict = validate_targets(
            conn, session_id="sid-1", targets=(str(target),),
        )
        assert verdict.allow is True
        assert str(repo) in verdict.repo_roots
