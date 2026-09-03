"""Runnable repository commands in session-cwd denial messages."""

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
from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_command_targets,
)


CURRENT_SESSION = "sid-current"
HOLDER_SESSION = "sid-holder"
CURRENT_ITEM = 7301
HELD_ITEM = 7302
FOREIGN_CWD = "/__mapped_other_project__"


@pytest.fixture
def conn():
    with test_database() as connection:
        yield connection


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    (path / ".worktrees").mkdir(parents=True)
    config_root = tmp_path / "machine-config"
    register_machine_checkout(config_root, path, 1)
    register_machine_checkout(
        config_root,
        Path(FOREIGN_CWD),
        2,
        create_checkout=False,
    )
    return path


def _seed_lane(conn, repo, *, item_id, session_id, branch):
    seed_item(conn, item_id=item_id, branch=branch, repo_path=repo)
    seed_item_claim(conn, session_id, item_id=item_id)
    lane = repo / ".worktrees" / branch
    lane.mkdir(parents=True, exist_ok=True)
    return lane


def _evaluate(command, *, session_id=CURRENT_SESSION, cwd=FOREIGN_CWD):
    return lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": session_id,
            "tool_name": "Bash",
            "cwd": cwd,
            "tool_input": {"command": command},
        }
    )


def _runnable_command(reason):
    lines = reason.splitlines()
    marker = lines.index("Runnable command:")
    return lines[marker + 2].strip()


class TestQuotedRepositorySelector:
    def test_exact_remote_selector_exposes_claimed_checkout(self):
        command = (
            "gh pr view 42 --repo "
            "\"$(git -C '/opt/claimed lane' remote get-url origin)\""
        )

        assert extract_command_targets(command) == ["/opt/claimed lane"]

    def test_extra_shell_action_is_not_trusted_as_a_selector(self):
        command = (
            'gh pr view 42 --repo "$(git -C /opt/claimed '
            'remote get-url origin; touch /opt/other)"'
        )

        assert extract_command_targets(command) == []

    @pytest.mark.parametrize(
        "command",
        [
            "echo '$(git -C /opt/claimed remote get-url origin)'",
            (
                'gh pr view 42 --repo "$(git -C /opt/claimed '
                'remote get-url origin)"; touch relative-file'
            ),
            (
                'gh pr view 42 --repo "$(git -C /opt/claimed '
                'remote get-url origin)$(touch relative-file)"'
            ),
        ],
    )
    def test_selector_text_outside_exact_gh_shape_is_not_trusted(self, command):
        assert extract_command_targets(command) == []


class TestClaimedLaneCommands:
    @pytest.mark.parametrize(
        "command",
        [
            "git add -A",
            "git commit -m 'save it'",
            "git push",
            "git worktree prune",
        ],
    )
    def test_targetless_git_write_names_exact_claimed_lane(
        self,
        conn,
        repo,
        command,
    ):
        lane = _seed_lane(
            conn,
            repo,
            item_id=CURRENT_ITEM,
            session_id=CURRENT_SESSION,
            branch="claimed-lane",
        )

        verdict = _evaluate(command)

        assert verdict.allow is False
        runnable = _runnable_command(verdict.reason)
        assert runnable.startswith(f"git -C {lane} ")
        assert _evaluate(runnable).allow is True

    def test_targetless_gh_command_names_claimed_repository(self, conn, repo):
        lane = _seed_lane(
            conn,
            repo,
            item_id=CURRENT_ITEM,
            session_id=CURRENT_SESSION,
            branch="claimed-lane",
        )

        verdict = _evaluate("gh pr view 42")

        assert verdict.allow is False
        command = _runnable_command(verdict.reason)
        assert command == (
            f'gh pr view 42 --repo "$(git -C {lane} remote get-url origin)"'
        )
        assert _evaluate(command).allow is True

    def test_targetless_gh_write_names_claimed_repository(self, conn, repo):
        lane = _seed_lane(
            conn,
            repo,
            item_id=CURRENT_ITEM,
            session_id=CURRENT_SESSION,
            branch="claimed-lane",
        )

        verdict = _evaluate("gh issue create --title example --body details")

        assert verdict.allow is False
        command = _runnable_command(verdict.reason)
        assert command.endswith(f'--repo "$(git -C {lane} remote get-url origin)"')
        assert _evaluate(command).allow is True

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git log --oneline",
            "git diff",
        ],
    )
    def test_targetless_git_reads_remain_allowed(self, conn, repo, command):
        _seed_lane(
            conn,
            repo,
            item_id=CURRENT_ITEM,
            session_id=CURRENT_SESSION,
            branch="claimed-lane",
        )

        assert _evaluate(command).allow is True

    def test_explicit_claimed_lane_remains_allowed(self, conn, repo):
        lane = _seed_lane(
            conn,
            repo,
            item_id=CURRENT_ITEM,
            session_id=CURRENT_SESSION,
            branch="claimed-lane",
        )

        assert _evaluate(f"git -C {lane} status").allow is True

    def test_arbitrary_shell_denial_offers_no_repository_command(
        self,
        conn,
        repo,
    ):
        _seed_lane(
            conn,
            repo,
            item_id=CURRENT_ITEM,
            session_id=CURRENT_SESSION,
            branch="claimed-lane",
        )

        verdict = _evaluate("python3 -m pip install example")

        assert verdict.allow is False
        assert "Runnable command:" not in verdict.reason

    def test_gh_local_checkout_offers_no_repository_command(self, conn, repo):
        _seed_lane(
            conn,
            repo,
            item_id=CURRENT_ITEM,
            session_id=CURRENT_SESSION,
            branch="claimed-lane",
        )

        verdict = _evaluate("gh pr checkout 42")

        assert verdict.allow is False
        assert "Runnable command:" not in verdict.reason


class TestForeignLaneCommands:
    def test_foreign_lane_write_offers_no_runnable_command(self, conn, repo):
        lane = _seed_lane(
            conn,
            repo,
            item_id=HELD_ITEM,
            session_id=HOLDER_SESSION,
            branch="held-lane",
        )

        verdict = _evaluate(f"git -C {lane} commit -m change")

        assert verdict.allow is False
        assert str(lane) in verdict.reason
        assert HOLDER_SESSION in verdict.reason
        assert "Runnable command:" not in verdict.reason

    def test_foreign_lane_git_read_needs_no_retarget(self, conn, repo):
        lane = _seed_lane(
            conn,
            repo,
            item_id=HELD_ITEM,
            session_id=HOLDER_SESSION,
            branch="held-lane",
        )

        assert _evaluate(f"git -C {lane} show HEAD --stat").allow is True

    def test_foreign_lane_file_read_names_exact_main_checkout(self, conn, repo):
        lane = _seed_lane(
            conn,
            repo,
            item_id=HELD_ITEM,
            session_id=HOLDER_SESSION,
            branch="held-lane",
        )

        verdict = _evaluate(f"cat {lane}/README.md")

        assert verdict.allow is False
        assert f"git -C {repo} show <rev>:<path>" in verdict.reason
        assert "Runnable command:" not in verdict.reason
