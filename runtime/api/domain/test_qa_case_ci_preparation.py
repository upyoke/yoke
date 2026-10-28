"""CI preparation diagnoses conflicts and carries a clean integration forward."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import (
    ci_case,
    completed_run,
    wire_ci_case,
)
from runtime.api.domain.test_qa_case_ci_source import git
from yoke_core.domain import (
    lane_base_update,
    qa_case_ci_covering_run,
    qa_case_ci_entry_run,
    qa_case_ci_lane,
    qa_case_ci_resume,
    qa_case_ci_run,
    verification_tree_binding,
)
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.engines import merge_worktree_pr_discovery, merge_worktree_pr_queue


@pytest.mark.parametrize(
    "state", ["dirty", "CONFLICTING", "clean", "unknown", "repaired"]
)
def test_missing_run_checks_landing_conflict_before_rebase(
    tmp_path, monkeypatch, state
):
    checkout, _, _ = wire_ci_case(tmp_path, monkeypatch)
    monkeypatch.setattr(qa_case_ci_lane, "ref_sha", lambda *a: "a" * 40)
    monkeypatch.setattr(
        qa_case_ci_entry_run, "routes_through_merge_queue", lambda p: True
    )
    monkeypatch.setattr(
        "yoke_core.domain.authored_file_merge_preflight.enforce_authored_file_limit",
        lambda *a, **k: None,
    )
    listing = Mock(
        return_value=merge_worktree_pr_discovery.BranchListing(rows=({"number": 213},))
    )
    monkeypatch.setattr(
        merge_worktree_pr_discovery, "list_branch_pull_requests", listing
    )
    monkeypatch.setattr(
        merge_worktree_pr_queue,
        "read_pr_landing_state",
        lambda *a: (
            SimpleNamespace(
                merge_state_status="dirty" if state == "repaired" else state,
                head_sha=("b" if state == "repaired" else "a") * 40,
            ),
            None,
        ),
    )
    rebase = Mock()
    monkeypatch.setattr(lane_base_update, "bring_lane_current", rebase)

    def prepare():
        return qa_case_ci_resume.prepare_lane_preserving_covering_run(
            checkout,
            project="example",
            repo="acme/widgets",
            workflow="ci.yml",
            branch="feature",
            lane_is_checked_out=True,
            requirement_id=41,
            timeout_seconds=60,
        )

    if state.upper() in {"DIRTY", "CONFLICTING"}:
        with pytest.raises(
            QaCaseExecutionError, match="qa_ci_pull_request_conflicting"
        ) as error:
            prepare()
        assert "pull request #213" in str(error.value)
        assert "merge origin/main" in str(error.value)
        assert "publish" in str(error.value) and "rerun" in str(error.value)
        rebase.assert_not_called()
    else:
        assert prepare().queue_target == "main"
        rebase.assert_called_once()
    assert listing.call_args.kwargs["query"] == {"state": "open", "base": "main"}


def test_clean_rebase_verifies_new_head_and_retains_requested_sha(
    tmp_path, monkeypatch
):
    checkout, recorder, _ = wire_ci_case(tmp_path, monkeypatch)
    git(checkout, "init", "-b", "main")
    git(checkout, "config", "user.name", "Test")
    git(checkout, "config", "user.email", "test@example.test")
    git(checkout, "commit", "--allow-empty", "-m", "base")
    git(checkout, "switch", "-c", "feature")
    (checkout / "feature.txt").write_text("feature")
    git(checkout, "add", "feature.txt")
    git(checkout, "commit", "-m", "feature")
    requested = git(checkout, "rev-parse", "HEAD")
    git(checkout, "switch", "main")
    (checkout / "base.txt").write_text("advanced")
    git(checkout, "add", "base.txt")
    git(checkout, "commit", "-m", "advance base")
    git(checkout, "switch", "feature")
    monkeypatch.setattr(
        qa_case_ci_lane, "ref_sha", lambda c, ref: git(c, "rev-parse", ref)
    )
    monkeypatch.setattr(
        qa_case_ci_lane,
        "checked_out_branch",
        lambda c: git(c, "branch", "--show-current"),
    )
    monkeypatch.setattr(
        verification_tree_binding,
        "resolve_tree_identity",
        lambda c: verification_tree_binding.TreeIdentity(
            str(c), git(c, "rev-parse", "HEAD")
        ),
    )
    monkeypatch.setattr(
        lane_base_update,
        "bring_lane_current",
        lambda c, **k: git(c, "rebase", "main"),
    )
    calls = []

    def covering(**kwargs):
        calls.append(kwargs["head_sha"])
        return None if len(calls) == 1 else completed_run(kwargs["head_sha"])

    monkeypatch.setattr(qa_case_ci_covering_run, "find_run_for_tree", covering)
    result = qa_case_ci_run.execute_ci_case(
        ci_case(lane_branch="feature", lane_path=str(checkout), lane_id=1, item_id=801),
        checkout_path=checkout,
        expected_branch="feature",
        expected_sha=requested,
    )
    rebased = git(checkout, "rev-parse", "HEAD")
    assert rebased != requested
    assert result["verdict"] == "pass"
    assert result["verification_tree"]["head_sha"] == rebased
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert evidence["requested_sha"] == requested
    assert evidence["verification_tree"]["head_sha"] == rebased
