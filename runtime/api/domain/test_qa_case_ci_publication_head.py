"""Immutable CI publication records only its proven live checkout's head."""

import subprocess
from contextlib import nullcontext

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import (
    ci_case,
    completed_run,
    wire_ci_case,
)
from yoke_cli.commands.adapters import project_snapshot
from yoke_core.domain import (
    merge_queue_push_safety,
    qa_case_ci_authority,
    qa_case_ci_covering_run,
    qa_case_ci_empty_diff,
    qa_case_ci_lane,
    qa_case_ci_resume,
    qa_case_ci_run,
    verification_tree_binding,
)
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


@pytest.fixture
def publication(tmp_path, monkeypatch):
    publish = qa_case_ci_lane.push_lane
    resolve = verification_tree_binding.resolve_tree_identity
    checkout, recorder, _ = wire_ci_case(tmp_path, monkeypatch)
    git(checkout, "init", "-b", "schema-worker")
    git(
        checkout,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=t@example.test",
        "commit",
        "--allow-empty",
        "-m",
        "candidate",
    )
    sha = git(checkout, "rev-parse", "HEAD")
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", str(origin)], check=True, capture_output=True
    )
    git(checkout, "remote", "add", "origin", str(origin))
    git_output = qa_case_ci_lane._git_output

    def immutable_push(root, *args, **kwargs):
        if args[0] == "push":
            assert args[-1] == f"{sha}:refs/heads/schema-worker"
        return git_output(root, *args, **kwargs)

    monkeypatch.setattr(qa_case_ci_lane, "_git_output", immutable_push)
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", publish)
    monkeypatch.setattr(verification_tree_binding, "resolve_tree_identity", resolve)
    monkeypatch.setattr(
        qa_case_ci_authority, "machine_github_user_authority", nullcontext
    )
    safety = []
    monkeypatch.setattr(
        merge_queue_push_safety,
        "require_publishable_lane",
        lambda **kw: safety.append(kw),
    )
    monkeypatch.setattr(
        qa_case_ci_resume,
        "prepare_lane_preserving_covering_run",
        lambda *a, **kw: qa_case_ci_resume.PreparedLane(queue_target=None),
    )
    monkeypatch.setattr(
        qa_case_ci_empty_diff, "record_pass_if_empty", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        qa_case_ci_covering_run,
        "find_run_for_tree",
        lambda **kw: completed_run(kw["head_sha"]),
    )
    stamps = []

    def snapshot(**kw):
        stamps.append((kw, git(kw["repo_root"], "rev-parse", "HEAD")))
        return {"status": "ok"}

    monkeypatch.setattr(project_snapshot, "sync_local_snapshot_for_write", snapshot)
    case = ci_case(
        item_id=801,
        lane_id=3,
        lane_branch="schema-worker",
        lane_path=str(checkout),
        lane_commit_sha=sha,
    )
    return checkout, origin, sha, case, stamps, safety, recorder


def test_execute_ci_publishes_full_sha_and_records_that_live_head(publication):
    checkout, origin, sha, case, stamps, safety, recorder = publication
    result = qa_case_ci_run.execute_ci_case(case, checkout_path=checkout)
    assert result["verdict"] == "pass"
    assert result["verification_tree"]["head_sha"] == sha
    assert git(origin, "rev-parse", "refs/heads/schema-worker") == sha
    assert safety[0]["head_sha"] == sha
    assert [(kw["repo_root"], head) for kw, head in stamps] == [(str(checkout), sha)]
    assert stamps[0][0]["head_only"] is True
    assert recorder.payload("qa.run.complete")["verdict"] == "pass"


@pytest.mark.parametrize(
    "mismatch", ["missing", "other-checkout", "branch", "head", "dirty"]
)
def test_published_sha_cannot_stamp_an_unproven_checkout(
    publication, monkeypatch, mismatch, capsys
):
    checkout, origin, sha, case, stamps, _, _ = publication
    if mismatch == "missing":
        case["lane_path"] = str(checkout / "missing-worker")
        from yoke_core.domain import project_checkout_locations

        monkeypatch.setattr(
            project_checkout_locations,
            "checkout_for_project_id",
            lambda _project: checkout,
        )
        monkeypatch.setattr(
            project_checkout_locations, "worktree_path_for_branch", lambda *_args: None
        )
    elif mismatch == "other-checkout":
        case["lane_path"] = str(origin)
        with pytest.raises(QaCaseExecutionError, match="qa_ci_source_mismatch"):
            qa_case_ci_run.execute_ci_case(case, checkout_path=checkout)
        assert stamps == []
        return
    else:
        push = qa_case_ci_lane._git_output

        def mutate_after_push(root, *args, **kw):
            result = push(root, *args, **kw)
            if args[0] == "push":
                if mismatch == "branch":
                    git(checkout, "switch", "-c", "another-worker")
                elif mismatch == "head":
                    git(
                        checkout,
                        "-c",
                        "user.name=Test",
                        "-c",
                        "user.email=t@example.test",
                        "commit",
                        "--allow-empty",
                        "-m",
                        "later local candidate",
                    )
                else:
                    (checkout / "untracked.txt").write_text("new work")
            return result

        monkeypatch.setattr(qa_case_ci_lane, "_git_output", mutate_after_push)
    result = qa_case_ci_run.execute_ci_case(case)
    assert result["verdict"] == "pass"
    assert git(origin, "rev-parse", "refs/heads/schema-worker") == sha
    assert stamps == []
    if mismatch in {"branch", "head", "dirty"}:
        assert "qa_published_head_unproven" in capsys.readouterr().err


def test_full_sha_stamp_preserves_snapshot_authorization_refusal(
    publication,
    monkeypatch,
    capsys,
):
    checkout, origin, sha, case, _, _, _ = publication
    monkeypatch.setattr(
        project_snapshot,
        "sync_local_snapshot_for_write",
        lambda **kw: {"status": "failed", "message": "actor cannot write"},
    )
    result = qa_case_ci_run.execute_ci_case(case, checkout_path=checkout)
    assert result["verdict"] == "pass"
    assert git(origin, "rev-parse", "refs/heads/schema-worker") == sha
    warning = capsys.readouterr().err
    assert "actor cannot write" in warning
    assert "project snapshot sync" in warning and "--head-only" in warning
