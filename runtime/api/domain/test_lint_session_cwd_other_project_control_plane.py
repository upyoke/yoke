"""A claim in one project must not revoke another project's control plane."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    project_id,
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import (
    lint_session_cwd,
    lint_session_cwd_control_plane,
    lint_session_cwd_validate,
)


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def fake_yoke_root(monkeypatch):
    yoke_root = Path("/__yoke_test_root__")
    monkeypatch.setattr(
        lint_session_cwd_control_plane,
        "yoke_main_root",
        lambda: str(yoke_root),
    )
    monkeypatch.setattr(
        lint_session_cwd_validate,
        "FREE_PATH_PREFIXES",
        ("/tmp", "/private/tmp", "/dev"),
    )
    return yoke_root


def _seed_two_projects(conn, fake_yoke_root):
    other = Path("/__other_project_repo__")
    register_machine_checkout(
        Path(tempfile.mkdtemp(prefix="yoke-machine-config-")),
        fake_yoke_root,
        project_id("yoke"),
        create_checkout=False,
    )
    seed_item(conn, item_id=801, branch="lane-a", repo_path=fake_yoke_root)
    seed_item_claim(conn, "sid-a", item_id=801)
    seed_item(
        conn,
        item_id=99,
        branch="EXT-99",
        repo_path=other,
        project="externalwebapp",
    )
    return other


def test_no_claims_allows_any_project_control_plane(conn):
    verdict = lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": "sid-none",
            "tool_input": {"file_path": "/__other_project_repo__/docs/README.md"},
        }
    )
    assert verdict.allow is True


def test_claim_in_a_allows_project_b_control_plane(conn, fake_yoke_root):
    other = _seed_two_projects(conn, fake_yoke_root)
    verdict = lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": "sid-a",
            "tool_input": {"file_path": str(other / "docs" / "README.md")},
        }
    )
    assert verdict.allow is True


def test_claim_in_a_allows_project_a_control_plane(conn, fake_yoke_root):
    _seed_two_projects(conn, fake_yoke_root)
    verdict = lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": "sid-a",
            "tool_input": {"file_path": str(fake_yoke_root / "docs" / "README.md")},
        }
    )
    assert verdict.allow is True


def test_claim_in_a_refuses_project_b_worktree(conn, fake_yoke_root):
    other = _seed_two_projects(conn, fake_yoke_root)
    verdict = lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": "sid-a",
            "tool_input": {
                "file_path": str(other / ".worktrees" / "EXT-99" / "src.py"),
            },
        }
    )
    assert verdict.allow is False


def test_claim_holder_own_worktree_still_allowed(conn, fake_yoke_root):
    _seed_two_projects(conn, fake_yoke_root)
    verdict = lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": "sid-a",
            "tool_input": {
                "file_path": str(fake_yoke_root / ".worktrees" / "lane-a" / "src.py"),
            },
        }
    )
    assert verdict.allow is True


def test_refusal_lists_both_project_roots(conn, fake_yoke_root):
    other = _seed_two_projects(conn, fake_yoke_root)
    verdict = lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": "sid-a",
            "tool_input": {"file_path": "/__foreign_target__/file"},
        }
    )
    assert verdict.allow is False
    assert "Any project control plane:" in verdict.reason
    assert str(fake_yoke_root) in verdict.reason
    assert str(other) in verdict.reason
