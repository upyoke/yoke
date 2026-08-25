"""Lane-main-write guard with several held lanes on one item.

An item claim covers every lane recorded under the item, so the guard
must treat a write into any held lane as a lane write, answer a main
write with a held lane, and point a write into an unheld lane at the
held lane's own path — never at a ``.worktrees`` nested inside a lane.
"""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.backlog_inserts import insert_item_worktree
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write
from yoke_core.domain.lint_lane_main_write_lanes import lane_equivalent_path
from yoke_core.domain.lint_lane_main_write_messages import (
    ESCAPE_TOKEN,
    format_denial,
)
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree

SESSION = "sid-multi-lane"
ITEM_ID = 510
LANES = (
    ("lane-hooks", "worker"),
    ("lane-relay", "worker"),
    ("lane-integration", "integration"),
)


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _seed_lanes(conn, repo):
    register_machine_checkout(
        repo.parent / "machine-config", repo, project_id=1,
    )
    seed_item(conn, item_id=ITEM_ID, branch=None, status="implementing")
    paths = []
    for branch, role in LANES:
        lane = repo / ".worktrees" / branch
        lane.mkdir(parents=True)
        insert_item_worktree(
            conn, item_id=ITEM_ID, branch=branch, lane_role=role,
            path=str(lane),
        )
        paths.append(lane)
    conn.commit()
    seed_item_claim(conn, SESSION, item_id=ITEM_ID)
    return paths


def _evaluate(payload):
    with mock.patch.object(
        lint_lane_main_write, "emit_denied", return_value=None,
    ):
        return lint_lane_main_write.evaluate_pre_tool_use(payload)


def _write(target):
    return {
        "session_id": SESSION,
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }


class TestHeldLanes:
    def test_write_inside_each_held_lane_is_a_lane_write(self, conn, repo):
        for lane in _seed_lanes(conn, repo):
            verdict = _evaluate(_write(lane / "src" / "module.py"))
            assert verdict.allow is True, lane

    def test_relative_write_from_a_held_lane_workdir(self, conn, repo):
        lanes = _seed_lanes(conn, repo)
        verdict = _evaluate({
            "session_id": SESSION,
            "tool_name": "Bash",
            "cwd": str(lanes[1]),
            "tool_input": {"command": "echo changed > src/module.py"},
        })
        assert verdict.allow is True


class TestRefusedTargets:
    def test_main_write_points_at_a_held_lane(self, conn, repo):
        lanes = _seed_lanes(conn, repo)
        target = repo / "runtime" / "api" / "foo.py"
        target.parent.mkdir(parents=True)
        verdict = _evaluate(_write(target))
        assert verdict.allow is False
        assert verdict.lane_equivalent == str(
            lanes[0] / "runtime" / "api" / "foo.py",
        )
        assert verdict.lane_equivalent.count(".worktrees") == 1

    def test_unheld_lane_write_points_at_the_held_lane(self, conn, repo):
        lanes = _seed_lanes(conn, repo)
        foreign = repo / ".worktrees" / "lane-foreign" / "src"
        foreign.mkdir(parents=True)
        verdict = _evaluate(_write(foreign / "module.py"))
        assert verdict.allow is False
        assert verdict.lane_equivalent == str(lanes[0] / "src" / "module.py")
        assert verdict.lane_equivalent.count(".worktrees") == 1


class TestLaneEquivalentPath:
    def test_foreign_lane_file_keeps_its_lane_relative_path(self, tmp_path):
        root = tmp_path / "repo"
        held = root / ".worktrees" / "held"
        held.mkdir(parents=True)
        claim = ClaimedWorktree(
            item_id=1, task_num=None, worktree_path=str(held),
        )
        other = root / ".worktrees" / "other" / "a" / "b.py"
        assert lane_equivalent_path(str(other), claim) == str(
            held / "a" / "b.py",
        )


class TestSessionIdentity:
    def test_env_fallback_prefers_the_codex_parent_session(self, monkeypatch):
        for name in ("YOKE_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("CODEX_SESSION_ID", "parent-thread")
        monkeypatch.setenv("CODEX_THREAD_ID", "child-thread")
        assert lint_lane_main_write._extract_session_id({}) == "parent-thread"


class TestApplyPatchGuidance:
    def test_apply_patch_denial_does_not_recommend_the_escape_token(self):
        text = format_denial(
            item_label="item", lane_path="/lane", attempted_path="/root/a.py",
            lane_equivalent="/lane/a.py", mode="deny",
            suppression_seen=False, tool_name="apply_patch",
        )
        assert f"add `{ESCAPE_TOKEN}`" not in text
        assert "apply_patch" in text
        assert "Edit/Write" in text

    def test_other_tools_keep_the_escape_recipe(self):
        text = format_denial(
            item_label="item", lane_path="/lane", attempted_path="/root/a.py",
            lane_equivalent="/lane/a.py", mode="deny",
            suppression_seen=False, tool_name="Write",
        )
        assert f"add `{ESCAPE_TOKEN}`" in text
