"""Read-only Git inspection of a lane another session holds.

A worker told to survey the neighbour it shares a file with runs ``git
status`` / ``git diff`` against the neighbour's tree. Those reads are
allowed; everything that writes or moves state in that lane stays
refused, and so does a shell shape that could smuggle a write past the
Git verb (a redirect, a chain, an ``--output`` file).

The caller in the observed failure holds its OWN lane claim, so the
allowance has to clear both halves of the policy: the ownership test
(somebody else holds this lane) and the authority test (a sibling lane
is outside every claim and outside the control plane).
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
from yoke_core.domain.lint_session_cwd_foreign_lane import (
    FAILURE_CLASS as FOREIGN_LANE_FAILURE_CLASS,
    is_read_only_git_inspection,
)


HOLDER = "sid-holder"
NEIGHBOUR = "sid-neighbour"
HELD_ITEM = 2240
NEIGHBOUR_ITEM = 2241

# Every verb the operator ruling allows, in the ``git -C <lane>`` form a
# neighbour survey actually types.
ALLOWED_COMMANDS = (
    "git -C {lane} status",
    "git -C {lane} status --short",
    "git -C {lane} diff",
    "git -C {lane} diff --stat HEAD~1",
    "git -C {lane} log --oneline -5",
    "git -C {lane} show HEAD --stat",
    "git -C {lane} ls-files",
    "git -C {lane} ls-tree HEAD",
    "git -C {lane} rev-parse HEAD",
    "git -C {lane} blame README.md",
    "git -C {lane} describe --tags",
    "git -C {lane} shortlog -n",
    "git -C {lane} branch",
    "git -C {lane} branch -a -vv",
    "git -C {lane} remote -v",
    "git -C {lane} config --list",
)

# Writes and state moves, plus the shell shapes that reach a write
# through an allowed verb.
REFUSED_COMMANDS = (
    "git -C {lane} checkout main",
    "git -C {lane} switch main",
    "git -C {lane} reset --soft HEAD~1",
    "git -C {lane} restore src/a.py",
    "git -C {lane} stash push -u -m parked",
    "git -C {lane} clean -fd",
    "git -C {lane} add .",
    "git -C {lane} commit -m wip",
    "git -C {lane} merge main",
    "git -C {lane} rebase main",
    "git -C {lane} cherry-pick abc1234",
    "git -C {lane} apply /tmp/patch.diff",
    "git -C {lane} worktree prune",
    "git -C {lane} branch -d topic",
    "git -C {lane} config user.email me@example.com",
    "git -C {lane} status > {lane}/status.txt",
    "git -C {lane} diff | tee {lane}/diff.txt",
    "git -C {lane} status && git -C {lane} add .",
    "git -C {lane} log --output={lane}/log.txt",
    "git -C {lane} log --output {lane}/log.txt",
    "ls {lane}",
    "cat {lane}/README.md",
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


def _seed_lane(conn, repo, *, session_id, item_id):
    register_machine_checkout(Path(repo).parent / "machine-config", Path(repo), 1)
    seed_item(conn, item_id=item_id, branch=f"YOK-{item_id}", repo_path=repo)
    seed_item_claim(conn, session_id, item_id=item_id)
    lane = repo / ".worktrees" / f"YOK-{item_id}"
    lane.mkdir(parents=True, exist_ok=True)
    return lane


def _neighbouring_lanes(conn, repo):
    """Return (held lane, the lane its neighbour session is working in)."""
    held = _seed_lane(conn, repo, session_id=HOLDER, item_id=HELD_ITEM)
    own = _seed_lane(conn, repo, session_id=NEIGHBOUR, item_id=NEIGHBOUR_ITEM)
    return held, own


def _bash_verdict(command: str, *, session_id: str = NEIGHBOUR):
    return lint_session_cwd.evaluate_pre_tool_use({
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {"command": command},
    })


class TestCommandClassification:
    """The classifier alone, with no lane or claim in the picture."""

    @pytest.mark.parametrize("command", ALLOWED_COMMANDS)
    def test_allowed_command_classifies_as_inspection(self, command):
        assert is_read_only_git_inspection(command.format(lane="/lane")) is True

    @pytest.mark.parametrize("command", REFUSED_COMMANDS)
    def test_refused_command_does_not_classify(self, command):
        assert is_read_only_git_inspection(command.format(lane="/lane")) is False

    def test_bare_git_status_classifies(self):
        assert is_read_only_git_inspection("git status") is True

    def test_env_prefixed_git_does_not_classify(self):
        assert is_read_only_git_inspection("GIT_PAGER=cat git status") is False

    def test_read_flag_resembling_output_still_classifies(self):
        assert is_read_only_git_inspection("git diff --output-indicator-new=+") is True

    def test_empty_command_does_not_classify(self):
        assert is_read_only_git_inspection("   ") is False


class TestNeighbourLaneInspection:
    @pytest.mark.parametrize("command", ALLOWED_COMMANDS)
    def test_allowed_while_holding_another_lane(self, conn, repo, command):
        held, _own = _neighbouring_lanes(conn, repo)
        verdict = _bash_verdict(command.format(lane=held))
        assert verdict.allow is True

    @pytest.mark.parametrize("command", ALLOWED_COMMANDS)
    def test_allowed_while_holding_no_claim_at_all(self, conn, repo, command):
        held = _seed_lane(conn, repo, session_id=HOLDER, item_id=HELD_ITEM)
        verdict = _bash_verdict(command.format(lane=held), session_id="sid-claimless")
        assert verdict.allow is True

    def test_allowed_when_the_lane_carries_no_live_claim(self, conn, repo):
        held, _own = _neighbouring_lanes(conn, repo)
        conn.execute(
            "UPDATE work_claims SET released_at = '2026-01-01T00:00:00Z' "
            "WHERE session_id = %s",
            (HOLDER,),
        )
        conn.commit()
        verdict = _bash_verdict(f"git -C {held} status")
        assert verdict.allow is True

    def test_inspection_of_own_lane_is_unaffected(self, conn, repo):
        _held, own = _neighbouring_lanes(conn, repo)
        verdict = _bash_verdict(f"git -C {own} diff --stat")
        assert verdict.allow is True


class TestNeighbourLaneWritesStillRefused:
    @pytest.mark.parametrize("command", REFUSED_COMMANDS)
    def test_refused_while_holding_another_lane(self, conn, repo, command):
        held, _own = _neighbouring_lanes(conn, repo)
        verdict = _bash_verdict(command.format(lane=held))
        assert verdict.allow is False
        assert verdict.failure_class == FOREIGN_LANE_FAILURE_CLASS

    def test_write_tool_into_the_lane_is_refused(self, conn, repo):
        held, _own = _neighbouring_lanes(conn, repo)
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": NEIGHBOUR,
            "tool_name": "Write",
            "tool_input": {"file_path": str(held / "src" / "a.py")},
        })
        assert verdict.allow is False
        assert verdict.failure_class == FOREIGN_LANE_FAILURE_CLASS

    def test_refusal_names_the_allowed_inspection_set(self, conn, repo):
        held, _own = _neighbouring_lanes(conn, repo)
        verdict = _bash_verdict(f"git -C {held} add .")
        assert "Read-only Git inspection of that lane IS allowed" in verdict.reason
        assert "git -C <lane> (" in verdict.reason
        assert "status" in verdict.reason
        assert "listing form only" in verdict.reason
