"""Explicit CI source mismatches refuse before preparation or publication."""

import subprocess
from unittest.mock import Mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import ci_case
from yoke_core.domain import qa_case_ci_run, qa_case_ci_lane, qa_case_ci_resume
from yoke_core.domain.qa_case_execution import (
    QaCaseExecutionError,
    execute_case_context,
)


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, text=True, capture_output=True
    ).stdout.strip()


@pytest.fixture
def source(tmp_path):
    git(tmp_path, "init", "-b", "schema-worker")
    git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.test",
        "commit",
        "--allow-empty",
        "-m",
        "source",
    )
    sha = git(tmp_path, "rev-parse", "HEAD")
    return (
        tmp_path,
        sha,
        ci_case(
            item_id=801,
            lane_id=3,
            lane_branch="schema-worker",
            lane_path=str(tmp_path),
            lane_commit_sha=sha,
        ),
    )


@pytest.mark.parametrize(
    "mismatch", ["checkout", "branch", "sha", "checked-out-branch", "old-contract"]
)
def test_source_mismatch_reaches_no_publisher(source, tmp_path, monkeypatch, mismatch):
    checkout, sha, case = source
    expected_branch, expected_sha = "schema-worker", sha
    if mismatch == "checkout":
        checkout = tmp_path / "other"
        checkout.mkdir()
    elif mismatch == "branch":
        expected_branch = "surfaces-worker"
    elif mismatch == "sha":
        expected_sha = "f" * 40
    elif mismatch == "checked-out-branch":
        git(checkout, "switch", "-c", "surfaces-worker")
    else:
        case.pop("lane_id")
    prepare = Mock(side_effect=AssertionError("must not prepare/publish"))
    publish = Mock(side_effect=AssertionError("must not push"))
    monkeypatch.setattr(
        qa_case_ci_resume, "prepare_lane_preserving_covering_run", prepare
    )
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", publish)
    with pytest.raises(QaCaseExecutionError, match="qa_ci_source_mismatch"):
        execute_case_context(
            case,
            checkout_path=checkout,
            expected_branch=expected_branch,
            expected_sha=expected_sha,
        )
    prepare.assert_not_called()
    publish.assert_not_called()


def test_matching_source_reaches_normal_preparation(source, monkeypatch):
    checkout, sha, case = source
    monkeypatch.setattr(qa_case_ci_lane, "repo_slug", lambda _root: "acme/widgets")
    prepare = Mock(side_effect=RuntimeError("normal preparation reached"))
    monkeypatch.setattr(
        qa_case_ci_resume, "prepare_lane_preserving_covering_run", prepare
    )
    with pytest.raises(RuntimeError, match="normal preparation reached"):
        qa_case_ci_run.execute_ci_case(
            case,
            checkout_path=checkout,
            expected_branch="schema-worker",
            expected_sha=sha,
        )
    prepare.assert_called_once()


def test_preparation_cannot_publish_a_changed_explicit_candidate(source, monkeypatch):
    checkout, sha, case = source
    monkeypatch.setattr(qa_case_ci_lane, "repo_slug", lambda _root: "acme/widgets")

    def prepare(*_args, **_kwargs):
        git(
            checkout,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "--allow-empty",
            "-m",
            "integrated source",
        )
        return qa_case_ci_resume.PreparedLane(queue_target=None)

    monkeypatch.setattr(
        qa_case_ci_resume, "prepare_lane_preserving_covering_run", prepare
    )
    publish = Mock(side_effect=AssertionError("must not publish changed source"))
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", publish)
    with pytest.raises(QaCaseExecutionError, match="qa_ci_source_mismatch"):
        qa_case_ci_run.execute_ci_case(
            case,
            checkout_path=checkout,
            expected_branch="schema-worker",
            expected_sha=sha,
        )
    publish.assert_not_called()


def test_case_entry_sends_selection_to_the_authoritative_context(source, monkeypatch):
    from yoke_core.domain import qa_case_execution
    from yoke_core.domain.qa_case_stage_credit import execute_authorized_case

    checkout, sha, case = source
    begin = Mock(return_value={"case": case})
    monkeypatch.setattr(qa_case_execution, "_dispatch", begin)
    monkeypatch.setattr(qa_case_ci_lane, "repo_slug", lambda _root: "acme/widgets")
    prepare = Mock(side_effect=RuntimeError("selected normal preparation"))
    monkeypatch.setattr(
        qa_case_ci_resume, "prepare_lane_preserving_covering_run", prepare
    )
    with pytest.raises(RuntimeError, match="selected normal preparation"):
        execute_authorized_case(
            case["requirement_id"],
            checkout_path=checkout,
            expected_branch="schema-worker",
            expected_sha=sha,
        )
    begin.assert_called_once_with(
        "qa.case_execution.begin",
        case["requirement_id"],
        {"checkout_path": str(checkout.resolve()), "expected_branch": "schema-worker"},
        actor=None,
    )


@pytest.mark.parametrize("recorded", [True, False])
def test_missing_lane_never_borrows_matching_parent_branch_head(source, recorded):
    from yoke_core.domain import qa_case_ci_source, verification_tree_binding

    checkout, sha, case = source
    case["lane_path"] = str(checkout / "missing-worker")
    case["lane_commit_sha"] = sha if recorded else None
    git(
        checkout,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.test",
        "commit",
        "--allow-empty",
        "-m",
        "parent checkout source",
    )
    parent_tree = verification_tree_binding.resolve_tree_identity(checkout)
    assert parent_tree.head_sha != sha
    if recorded:
        tree = qa_case_ci_source.source_tree(
            case, checkout, "schema-worker", "schema-worker", parent_tree
        )
        assert tree.head_sha == sha
    else:
        with pytest.raises(QaCaseExecutionError, match="no recorded commit"):
            qa_case_ci_source.source_tree(
                case, checkout, "schema-worker", "schema-worker", parent_tree
            )
