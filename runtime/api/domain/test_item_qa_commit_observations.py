"""Item-scoped proof is independent of its recorded start commit."""

import pytest
from yoke_core.domain.qa_terminal_settlement import blocking_requirement_issues
from yoke_core.domain.standalone_item_merge_qa import evaluate
from runtime.api.domain.test_standalone_item_merge_qa import _item, _requirement


@pytest.mark.parametrize("sha", ["a" * 40, "b" * 40, "", None])
@pytest.mark.parametrize("runner", [None, "worktree_run", "ci_run", "agent_mission", "host_control", "browser_substrate"])
def test_item_pass_counts_without_commit_comparison(tmp_path, sha, runner):
    row = _requirement(verdict="pass", sha=sha)
    row.update(runner_id=runner, current_passing_proof=True, subject_proof_error="")
    item = _item(row)
    head, issues, error = evaluate(item, public_ref="example", repo_root=tmp_path, branch="lane")
    assert head == item["worktrees"][0]["commit_sha"]
    assert (issues, error) == ([], "")
    assert blocking_requirement_issues([row], public_ref="example", require_any=True) == []


@pytest.mark.parametrize("field,value,state", [
    ("verdict", "fail", "incomplete"),
    ("completed_at", None, "incomplete"),
    ("current_passing_proof", False, "stale-proof"),
    ("subject_proof_error", "qa_machine_admission_unproven", "subject-unproven"),
])
def test_other_proof_still_blocks(field, value, state):
    row = _requirement(verdict="pass", sha="")
    row[field] = value
    [issue] = blocking_requirement_issues([row], public_ref="example", require_any=True)
    assert issue.state == state
