"""Status-gate scenarios for the session-cwd lint."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import (
    lint_session_cwd,
    lint_session_cwd_pre_implementing,
    lint_session_cwd_status,
)


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"projects": {str(repo_path): {"project_id": 1}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))
    return repo_path


def _seed(conn, repo_path, *, item_id, status, branch="YOK-9001"):
    del repo_path
    seed_item(conn, item_id=item_id, branch=branch, status=status)
    seed_item_claim(conn, "sid-1", item_id)


@pytest.fixture
def silenced_emit(monkeypatch):
    captured = []

    def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(
        lint_session_cwd_pre_implementing,
        "emit_pre_implementing_status",
        _capture,
    )
    return captured


@pytest.fixture
def deny_mode(monkeypatch):
    monkeypatch.setattr(
        lint_session_cwd_pre_implementing, "read_mode", lambda: "deny",
    )


@pytest.fixture
def warn_mode(monkeypatch):
    monkeypatch.setattr(
        lint_session_cwd_pre_implementing, "read_mode", lambda: "warn",
    )


# ---------------------------------------------------------------------------
# Pre-implementing status + worktree write → denied
# Implementing-class + worktree write → allowed
# ---------------------------------------------------------------------------


class TestPreImplementingDenied:
    def test_refined_idea_status_denies_worktree_write(
        self, conn, repo, deny_mode, silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)
        target = wt / "src/file.py"
        target.parent.mkdir(parents=True)
        target.write_text("# stub")

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"file_path": str(target)},
        })

        assert verdict.allow is False
        assert verdict.failure_class == "pre_implementing_status"
        assert verdict.item_id == 9001
        assert verdict.item_status == "refined-idea"
        assert verdict.mode == "deny"
        assert verdict.suppression_attempted is False
        # Denial body names the item + status + recovery commands.
        assert "BLOCKED" in verdict.reason
        assert "YOK-9001" in verdict.reason
        assert "refined-idea" in verdict.reason
        assert "/yoke advance YOK-9001 implementation" in verdict.reason
        assert "finalize.md step 6" in verdict.reason
        assert len(silenced_emit) == 1
        emitted = silenced_emit[0]
        assert emitted["outcome"] == "blocked"
        assert emitted["item_id"] == 9001
        assert emitted["status"] == "refined-idea"
        assert emitted["mode"] == "deny"

    @pytest.mark.parametrize(
        "status", ["idea", "refining-idea", "planning",
                   "plan-drafted", "refining-plan", "planned"],
    )
    def test_every_pre_implementing_status_denies(
        self, conn, repo, deny_mode, silenced_emit, status,
    ):
        _seed(conn, repo, item_id=9001, status=status)
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)
        target = wt / "any.py"
        target.write_text("# stub")

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"file_path": str(target)},
        })

        assert verdict.allow is False
        assert verdict.failure_class == "pre_implementing_status"
        assert verdict.item_status == status


class TestImplementingClassAllowed:
    @pytest.mark.parametrize(
        "status",
        ["implementing", "reviewing-implementation",
         "polishing-implementation"],
    )
    def test_implementing_class_allows_worktree_write(
        self, conn, repo, deny_mode, silenced_emit, status,
    ):
        _seed(conn, repo, item_id=9001, status=status)
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)
        target = wt / "any.py"
        target.write_text("# stub")

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"file_path": str(target)},
        })

        assert verdict.allow is True
        # No deny payload, no audit event for the happy path.
        assert silenced_emit == []


# ---------------------------------------------------------------------------
# Main control-plane + free-path writes are unaffected
# ---------------------------------------------------------------------------


class TestStatusGateScope:
    def test_control_plane_write_unaffected_by_status(
        self, conn, repo, deny_mode, silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        (repo / ".worktrees" / "YOK-9001").mkdir(parents=True)
        target = repo / "docs/README.md"
        target.parent.mkdir(parents=True)
        target.write_text("# stub")

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"file_path": str(target)},
        })

        assert verdict.allow is True
        assert silenced_emit == []

    def test_free_path_write_unaffected_by_status(
        self, conn, repo, deny_mode, silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        (repo / ".worktrees" / "YOK-9001").mkdir(parents=True)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"file_path": "/tmp/yoke-cmd.txt"},
        })

        assert verdict.allow is True
        assert silenced_emit == []


# ---------------------------------------------------------------------------
# Mode pinned by machine config (warn vs deny)
# ---------------------------------------------------------------------------


class TestWarnMode:
    def test_warn_mode_records_audit_and_allows(
        self, conn, repo, warn_mode, silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)
        target = wt / "any.py"
        target.write_text("# stub")

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"file_path": str(target)},
        })

        # Warn mode does NOT block.
        assert verdict.allow is True
        assert verdict.mode == "warn"
        # Audit event still emitted with outcome=warn.
        assert len(silenced_emit) == 1
        assert silenced_emit[0]["outcome"] == "warn"
        assert silenced_emit[0]["status"] == "refined-idea"


# ---------------------------------------------------------------------------
# Suppression token is audit-only; the rule still denies.
# ---------------------------------------------------------------------------


class TestSuppressionToken:
    def test_suppression_token_does_not_unblock(
        self, conn, repo, deny_mode, silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)

        token = lint_session_cwd_status.SUPPRESSION_TOKEN
        command = f"cat > {wt}/notes.py  {token}"
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"command": command},
        })

        # Deny still fires.
        assert verdict.allow is False
        assert verdict.suppression_attempted is True
        # Audit event distinguishes "suppression attempted".
        assert len(silenced_emit) == 1
        assert silenced_emit[0]["outcome"] == "suppression_attempted"

    def test_command_without_token_records_blocked(
        self, conn, repo, deny_mode, silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"command": f"echo hi > {wt}/notes.py"},
        })

        assert verdict.allow is False
        assert verdict.suppression_attempted is False
        assert silenced_emit[0]["outcome"] == "blocked"


# ---------------------------------------------------------------------------
# Audit-event context payload coverage
# ---------------------------------------------------------------------------


class TestAuditPayload:
    def test_audit_event_carries_required_fields(
        self, conn, repo, deny_mode, silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)
        target = wt / "any.py"
        target.write_text("# stub")

        lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "tool_input": {"file_path": str(target)},
        })

        assert len(silenced_emit) == 1
        kwargs = silenced_emit[0]
        # All five context fields required by AC-8 are present.
        assert kwargs["session_id"] == "sid-1"
        assert kwargs["item_id"] == 9001
        assert kwargs["status"] == "refined-idea"
        assert kwargs["mode"] == "deny"
        assert "target_path" in kwargs
        # The validator's resolved target should appear in target_path.
        assert kwargs["target_path"].endswith("any.py")
