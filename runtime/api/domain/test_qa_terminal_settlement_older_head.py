"""Lane ancestry authorizes older passes without rebinding or rerunning."""

import argparse
import subprocess

import pytest

from yoke_core.domain.qa_lane_history import checkout_contains
from yoke_core.domain.qa_terminal_settlement import blocking_requirement_issues
from yoke_core.domain.standalone_item_merge_qa import evaluate
from yoke_core.domain.standalone_item_merge_verify import proof_check
from runtime.api.domain.test_standalone_item_merge_qa import _item, _requirement


@pytest.fixture
def history(tmp_path):
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(tmp_path), *args], text=True
        ).strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.test")
    git("commit", "--allow-empty", "-qm", "start")
    start = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-qm", "later")
    head = git("rev-parse", "HEAD")
    git("checkout", "-q", "--orphan", "foreign")
    git("commit", "--allow-empty", "-qm", "foreign")
    foreign = git("rev-parse", "HEAD")
    return tmp_path, start, head, foreign


@pytest.mark.parametrize(
    "runner",
    [
        None,
        "worktree_run",
        "ci_run",
        "agent_mission",
        "host_control",
        "browser_substrate",
    ],
)
def test_earlier_lane_pass_authorizes_merge_and_terminal(history, runner):
    root, start, head, _ = history
    row = _requirement(verdict="pass", sha=start)
    row.update(runner_id=runner, subject_proof_error="", current_passing_proof=True)
    item = _item(row)
    item["worktrees"][0]["commit_sha"] = head
    assert evaluate(item, public_ref="example", repo_root=root, branch="lane") == (
        head,
        [],
        "",
    )
    assert (
        blocking_requirement_issues(
            [row],
            accepted_shas=(head,),
            public_ref="example",
            require_any=True,
            contains_commit=lambda h, c: checkout_contains(str(root), h, c),
        )
        == []
    )


def test_foreign_pass_refuses_with_commit_and_recovery(history):
    root, _, head, foreign = history
    item = _item(_requirement(verdict="pass", sha=foreign))
    item["worktrees"][0]["commit_sha"] = head
    _, [issue], _ = evaluate(item, public_ref="example", repo_root=root, branch="lane")
    assert issue.state == "outside-lane"
    assert foreign in issue.detail
    assert "claimed lane" in issue.detail
    blocker, note = proof_check(
        item,
        argparse.Namespace(skip_status=False),
        public_ref="example",
        repo_root=root,
        branch="lane",
    )
    assert "outside-lane" in blocker
    assert note == ""


@pytest.mark.parametrize("verdict", ["fail", "error", None])
def test_latest_failure_or_incomplete_attempt_blocks(history, verdict):
    root, start, head, _ = history
    row = _requirement(verdict=verdict, sha=start)
    item = _item(row)
    item["worktrees"][0]["commit_sha"] = head
    _, [issue], _ = evaluate(item, public_ref="example", repo_root=root, branch="lane")
    assert issue.state == "incomplete"


@pytest.mark.parametrize(
    "field,value,state",
    [
        ("current_passing_proof", False, "stale-proof"),
        ("subject_proof_error", "qa_machine_admission_unproven", "subject-unproven"),
    ],
)
def test_ancestry_does_not_discharge_other_proof(history, field, value, state):
    root, start, head, _ = history
    row = _requirement(verdict="pass", sha=start)
    row[field] = value
    item = _item(row)
    item["worktrees"][0]["commit_sha"] = head
    _, [issue], _ = evaluate(item, public_ref="example", repo_root=root, branch="lane")
    assert issue.state == state
