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


def _seed(
    conn,
    repo_path,
    *,
    item_id,
    status,
    branch="YOK-9001",
    workflow_id="issue",
):
    seed_item(
        conn,
        item_id=item_id,
        branch=branch,
        repo_path=repo_path,
        status=status,
        workflow_id=workflow_id,
    )
    seed_item_claim(conn, "sid-1", item_id)


def _call(tool_name, tool_input):
    return lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": "sid-1",
            "tool_name": tool_name,
            "tool_input": tool_input,
        }
    )


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
        lint_session_cwd_pre_implementing,
        "read_mode",
        lambda: "deny",
    )


@pytest.fixture
def warn_mode(monkeypatch):
    monkeypatch.setattr(
        lint_session_cwd_pre_implementing,
        "read_mode",
        lambda: "warn",
    )


class TestPreImplementingDenied:
    def test_refined_idea_status_denies_worktree_write(
        self,
        conn,
        repo,
        deny_mode,
        silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)
        target = wt / "src/file.py"
        target.parent.mkdir(parents=True)
        target.write_text("# stub")

        verdict = _call("Write", {"file_path": str(target)})

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
        assert "/yoke implement YOK-9001" in verdict.reason
        assert "yoke lifecycle transition YOK-9001 --to implementing" in verdict.reason
        assert "advance" not in verdict.reason
        assert len(silenced_emit) == 1
        emitted = silenced_emit[0]
        assert emitted["outcome"] == "blocked"
        assert emitted["item_id"] == 9001
        assert emitted["status"] == "refined-idea"
        assert emitted["mode"] == "deny"

    @pytest.mark.parametrize(
        "workflow_id,status",
        [
            ("issue", "idea"),
            ("issue", "refining-idea"),
            ("epic", "planning"),
            ("epic", "plan-drafted"),
            ("epic", "refining-plan"),
            ("epic", "planned"),
        ],
    )
    def test_every_pre_implementing_status_denies(
        self,
        conn,
        repo,
        deny_mode,
        silenced_emit,
        workflow_id,
        status,
    ):
        _seed(
            conn,
            repo,
            item_id=9001,
            status=status,
            workflow_id=workflow_id,
        )
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)
        target = wt / "any.py"
        target.write_text("# stub")

        verdict = _call("Write", {"file_path": str(target)})

        assert verdict.allow is False
        assert verdict.failure_class == "pre_implementing_status"
        assert verdict.item_status == status


class TestImplementingClassAllowed:
    @pytest.mark.parametrize(
        "status",
        ["implementing", "reviewing-implementation", "polishing-implementation"],
    )
    def test_implementing_class_allows_worktree_write(
        self,
        conn,
        repo,
        deny_mode,
        silenced_emit,
        status,
    ):
        _seed(conn, repo, item_id=9001, status=status)
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)
        target = wt / "any.py"
        target.write_text("# stub")

        verdict = _call("Write", {"file_path": str(target)})

        assert verdict.allow is True
        assert silenced_emit == []


class TestStatusGateScope:
    def test_control_plane_write_unaffected_by_status(
        self,
        conn,
        repo,
        deny_mode,
        silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        (repo / ".worktrees" / "YOK-9001").mkdir(parents=True)
        target = repo / "docs/README.md"
        target.parent.mkdir(parents=True)
        target.write_text("# stub")

        verdict = _call("Write", {"file_path": str(target)})

        assert verdict.allow is True
        assert silenced_emit == []

    def test_free_path_write_unaffected_by_status(
        self,
        conn,
        repo,
        deny_mode,
        silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        (repo / ".worktrees" / "YOK-9001").mkdir(parents=True)

        verdict = _call("Write", {"file_path": "/tmp/yoke-cmd.txt"})

        assert verdict.allow is True
        assert silenced_emit == []


class TestWarnMode:
    def test_warn_mode_records_audit_and_allows(
        self,
        conn,
        repo,
        warn_mode,
        silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)
        target = wt / "any.py"
        target.write_text("# stub")

        verdict = _call("Write", {"file_path": str(target)})

        assert verdict.allow is True
        assert verdict.mode == "warn"
        assert len(silenced_emit) == 1
        assert silenced_emit[0]["outcome"] == "warn"
        assert silenced_emit[0]["status"] == "refined-idea"


class TestSuppressionToken:
    def test_suppression_token_does_not_unblock(
        self,
        conn,
        repo,
        deny_mode,
        silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)

        token = lint_session_cwd_status.SUPPRESSION_TOKEN
        command = f"cat > {wt}/notes.py  {token}"
        verdict = _call("Bash", {"command": command})

        assert verdict.allow is False
        assert verdict.suppression_attempted is True
        assert len(silenced_emit) == 1
        assert silenced_emit[0]["outcome"] == "suppression_attempted"

    def test_command_without_token_records_blocked(
        self,
        conn,
        repo,
        deny_mode,
        silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)

        verdict = _call("Bash", {"command": f"echo hi > {wt}/notes.py"})

        assert verdict.allow is False
        assert verdict.suppression_attempted is False
        assert silenced_emit[0]["outcome"] == "blocked"


class TestAuditPayload:
    def test_audit_event_carries_required_fields(
        self,
        conn,
        repo,
        deny_mode,
        silenced_emit,
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        wt = repo / ".worktrees" / "YOK-9001"
        wt.mkdir(parents=True)
        target = wt / "any.py"
        target.write_text("# stub")

        _call("Write", {"file_path": str(target)})

        assert len(silenced_emit) == 1
        kwargs = silenced_emit[0]
        assert kwargs["session_id"] == "sid-1"
        assert kwargs["item_id"] == 9001
        assert kwargs["status"] == "refined-idea"
        assert kwargs["mode"] == "deny"
        assert "target_path" in kwargs
        # The validator's resolved target should appear in target_path.
        assert kwargs["target_path"].endswith("any.py")
