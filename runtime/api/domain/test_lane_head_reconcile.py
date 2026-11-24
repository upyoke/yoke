"""Lane reconciliation exercises Git without relying on installed hooks."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yoke_core.domain import lane_head_record


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, text=True, capture_output=True
    ).stdout.strip()


@pytest.fixture
def lane(tmp_path):
    git(tmp_path, "init", "-b", "lane")
    git(tmp_path, "config", "user.email", "lane@example.org")
    git(tmp_path, "config", "user.name", "Lane")
    git(tmp_path, "config", "core.hooksPath", str(tmp_path / "disabled-hooks"))
    git(tmp_path, "commit", "--allow-empty", "-m", "base")
    return {"path": tmp_path, "branch": "lane", "commit_sha": git(tmp_path, "rev-parse", "HEAD")}


@pytest.mark.parametrize("move", ["commit", "rebase", "reset"])
def test_git_move_wins_over_the_record(lane, monkeypatch, move):
    checkout = lane["path"]
    git(checkout, "commit", "--allow-empty", "-m", "lane work")
    if move == "reset":
        lane["commit_sha"] = git(checkout, "rev-parse", "HEAD")
        git(checkout, "reset", "--hard", "HEAD~1")
    if move == "rebase":
        lane["commit_sha"] = git(checkout, "rev-parse", "HEAD")
        git(checkout, "switch", "-c", "base", "HEAD~1")
        git(checkout, "commit", "--allow-empty", "-m", "new base")
        git(checkout, "switch", "lane")
        git(checkout, "rebase", "--keep-empty", "base")
    head = git(checkout, "rev-parse", "HEAD")
    assert head != lane["commit_sha"]
    written = []

    def record(project, path, **kwargs):
        written.append((project, path, kwargs["expected_head"]))
        return ""

    monkeypatch.setattr(lane_head_record, "record_lane_head", record)
    assert lane_head_record.reconcile_lane_head("example", lane) == (head, "")
    assert written == [("example", str(checkout), head)]


@pytest.mark.parametrize("location", ["same", "absent", "unreadable"])
def test_unchanged_or_unavailable_checkout_does_not_write(lane, monkeypatch, location):
    if location != "same":
        lane["path"] /= "not-a-checkout"
    if location == "unreadable":
        lane["path"].mkdir()
    monkeypatch.setattr(lane_head_record, "record_lane_head", lambda *a, **k: pytest.fail("write"))
    head, error = lane_head_record.reconcile_lane_head("example", lane)
    assert not head
    if location == "unreadable":
        assert "lane_head_unreadable" in error
        assert "repair the Git checkout" in error
        assert str(lane["path"]) in error
    else:
        assert not error


@pytest.mark.parametrize("state", ["rebase", "merge", "branch"])
def test_unstable_checkout_refuses_before_write(lane, monkeypatch, state):
    checkout = lane["path"]
    code = f"lane_head_{state}_in_progress"
    if state == "branch":
        git(checkout, "switch", "-c", "other")
        code = "lane_head_branch_mismatch"
    else:
        marker = "rebase-merge" if state == "rebase" else "MERGE_HEAD"
        (checkout / git(checkout, "rev-parse", "--git-path", marker)).touch()
    monkeypatch.setattr(lane_head_record, "record_lane_head", lambda *a, **k: pytest.fail("write"))
    head, error = lane_head_record.reconcile_lane_head("example", lane)
    assert not head
    assert error.startswith(code)
    assert "rerun the same command" in error


@pytest.mark.parametrize("status", ["failed", "deferred", "ok"])
def test_missing_write_confirmation_refuses(lane, monkeypatch, status):
    monkeypatch.setattr(lane_head_record, "required_project", lambda *a, **k: "example")
    monkeypatch.setattr(lane_head_record, "get_project_snapshot", lambda: SimpleNamespace(
        sync_local_snapshot_for_write=lambda **kwargs: {"status": status},
    ))
    head, error = lane_head_record.reconcile_lane_head("example", {**lane, "commit_sha": "a" * 40})
    assert not head
    assert error.startswith("lane_head_unrecorded:")
    assert "rerun the same command" in error


def test_relay_uses_registered_head_only_write(lane, monkeypatch):
    from yoke_cli.commands.adapters import project_snapshot
    from yoke_contracts.api.function_call import FunctionCallResponse

    monkeypatch.setattr(lane_head_record, "required_project", lambda *a, **k: "example")
    monkeypatch.setattr(project_snapshot, "_project_context", lambda project: project)
    monkeypatch.setattr(project_snapshot, "assert_project_repository", lambda *a, **k: None)
    monkeypatch.setattr(project_snapshot, "ensure_handlers_loaded", lambda: None)
    calls = []

    def dispatch(**call):
        calls.append(call)
        return FunctionCallResponse(
            success=True, function="project.snapshot.sync", version="v1",
            result={"snapshots": [{
                "ref": "HEAD", "commit_sha": lane["commit_sha"], "lane_head_recorded": True,
            }]},
        )

    monkeypatch.setattr(project_snapshot, "call_dispatcher", dispatch)
    assert lane_head_record.reconcile_lane_head(
        "example", {**lane, "commit_sha": "a" * 40}
    ) == (lane["commit_sha"], "")
    assert len(calls) == 1
    assert calls[0]["function_id"] == "project.snapshot.sync"
    assert calls[0]["target"].project_id == "example"
    assert calls[0]["payload"]["snapshots"][0]["commit_sha"] == lane["commit_sha"]
