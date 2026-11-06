"""Candidate refresh precedes commit-bound merge readiness."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import standalone_item_merge_cli as cli


@pytest.mark.parametrize("check", [False, True])
def test_readiness_uses_refreshed_item_only_for_actual_merge(monkeypatch, check):
    stale = {"id": 7, "public_ref": "ITEM-7", "workflow": {"id": "dash"}}
    fresh = {**stale, "worktrees": [{"commit_sha": "a" * 40}]}
    events = []
    monkeypatch.setattr(cli, "_resolve_item", lambda *_a: (stale, ""))
    monkeypatch.setattr(cli.report, "bind", lambda **_k: lambda *_a, **_kw: None)
    def refresh(item, resolve):
        assert item is stale
        assert resolve() == (stale, "")
        events.append("refresh")
        return fresh, ""
    def assess(item, *_a, **_k):
        assert item is (stale if check else fresh)
        events.append("readiness")
        return SimpleNamespace(ready=False, refusal=lambda: "stop at readiness")
    monkeypatch.setattr(cli, "refresh_recorded_head", refresh)
    monkeypatch.setattr(cli.readiness_gate, "assess", assess)
    monkeypatch.setattr(cli.readiness_gate, "print_check", lambda *_a, **_k: 1)
    monkeypatch.setattr(cli.report, "fail_json", lambda *_a, **_k: 1)
    assert cli.run(["ITEM-7"] + (["--check"] if check else [])) == 1
    assert events == (["readiness"] if check else ["refresh", "readiness"])


def test_recording_refusal_never_reaches_readiness(monkeypatch):
    item = {"id": 7, "public_ref": "ITEM-7", "workflow": {"id": "dash"}}
    monkeypatch.setattr(cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(cli.report, "bind", lambda **_k: lambda *_a, **_kw: None)
    monkeypatch.setattr(cli, "refresh_recorded_head", lambda *_a: (item, "record failed"))
    monkeypatch.setattr(cli.readiness_gate, "assess", lambda *_a, **_k: pytest.fail("readiness ran"))
    errors = []
    monkeypatch.setattr(cli.report, "fail_json", lambda message, **_k: errors.append(message) or 1)
    assert cli.run(["ITEM-7"]) == 1
    assert errors == ["record failed"]


def test_unrecorded_correction_lands_and_publishes_after_red_post_push(tmp_path, monkeypatch):
    from runtime.api.domain.standalone_merge_simulation_support import git, make_checkout
    from yoke_core.domain import lane_head_record
    from yoke_core.domain import standalone_item_merge as merging
    from yoke_core.domain import standalone_item_merge_lane as lane
    from yoke_core.domain import standalone_item_merge_post_push as post_push

    root = make_checkout(tmp_path)
    remote = tmp_path / "origin.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "origin", "main")
    first = git(root, "rev-parse", "ITEM-1")
    monkeypatch.setattr(merging.receipts, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(merging.receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(merging.receipts, "record_before_landing", lambda *_a, **_k: "")
    monkeypatch.setattr(merging, "stamp_merged_at", lambda *_a, **_k: "")
    monkeypatch.setattr(post_push, "github_merge_enabled", lambda *_a: True)
    monkeypatch.setattr(post_push, "fast_forward_main_checkout", lambda *_a: "")
    observed = []
    verdicts = iter(("failed", "passed"))
    def checks(_project, sha, _authority):
        observed.append(sha)
        return post_push.PostPushVerdict(next(verdicts))
    monkeypatch.setattr(post_push, "await_post_push_checks", checks)
    def engine(**kwargs):
        git(root, "checkout", "main")
        git(root, "merge", "--ff-only", kwargs["source_sha"])
        return 0, ""
    monkeypatch.setattr(merging, "_run_merge_engine", engine)
    def merge(sha):
        return merging.merge_standalone_branch(
            item_id=7, branch="ITEM-1", target="main", repo_root=str(root),
            project="example", commit_sha=sha,
        )
    assert not merge(first).ok
    git(root, "checkout", "ITEM-1")
    (root / "repair.txt").write_text("correction after red CI\n")
    git(root, "add", "repair.txt")
    git(root, "commit", "-m", "repair")
    repair = git(root, "rev-parse", "HEAD")
    item = {"project": {"slug": "example"}, "worktrees": [
        {"branch": "ITEM-1", "path": str(root), "commit_sha": first}
    ]}
    def record(*_a):
        item["worktrees"][0]["commit_sha"] = repair
        return ""
    monkeypatch.setattr(lane_head_record, "record_lane_head", record)
    refreshed, error = lane.refresh_recorded_head(item, lambda: (item, ""))
    assert not error
    outcome = merge(refreshed["worktrees"][0]["commit_sha"])
    assert outcome.ok and outcome.pushed and not outcome.already_merged
    assert outcome.commit_sha == repair
    assert git(remote, "rev-parse", "main") == repair
    assert observed == [first, repair]
