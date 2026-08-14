"""Unit coverage for the yoke-ci same-tree reuse probe."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from typing import Any
from urllib.error import URLError

import pytest

from yoke_core.tools import yoke_ci_tree_reuse as probe


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(cwd), *args],
        text=True,
    ).strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@yoke.local")
    _git(repo, "config", "user.name", "Yoke CI")
    # Older git still defaults to `master`; normalize so later checkouts work.
    _git(repo, "checkout", "-B", "main")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "first")
    return repo


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_decide_reuse_skips_when_dispatch_run_shares_tree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    now = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)
    runs = {
        "workflow_runs": [
            {
                "id": 100,
                "event": "workflow_dispatch",
                "head_sha": head,
                "created_at": "2026-08-07T17:00:00Z",
                "html_url": "https://example.test/runs/100",
            }
        ]
    }

    def opener(request: Any, timeout: float = 0) -> _FakeResponse:
        assert "actions/workflows/yoke-ci.yml/runs" in request.full_url
        return _FakeResponse(runs)

    decision = probe.decide_reuse(
        worktree=repo,
        api_url="https://api.github.com",
        repository="upyoke/yoke",
        token="token",
        current_run_id=999,
        window_hours=24,
        now=now,
        opener=opener,
    )

    assert decision.skip_suite is True
    assert decision.candidate_tree == tree
    assert decision.covering_run_id == 100
    assert decision.covering_head_sha == head
    assert decision.reason == "identical_tree"


def test_decide_reuse_runs_suite_for_distinct_merge_tree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    covered = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "feature")
    (repo / "b.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", "feature")
    _git(repo, "checkout", "main")
    (repo / "c.txt").write_text("mainline\n", encoding="utf-8")
    _git(repo, "add", "c.txt")
    _git(repo, "commit", "-m", "mainline")
    _git(repo, "merge", "--no-ff", "feature", "-m", "merge feature")
    merge_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    covered_tree = probe.tree_object_id(repo, covered)
    assert covered_tree is not None
    assert covered_tree != merge_tree

    now = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)
    runs = {
        "workflow_runs": [
            {
                "id": 100,
                "event": "workflow_dispatch",
                "head_sha": covered,
                "created_at": "2026-08-07T17:00:00Z",
                "html_url": "https://example.test/runs/100",
            }
        ]
    }

    decision = probe.decide_reuse(
        worktree=repo,
        api_url="https://api.github.com",
        repository="upyoke/yoke",
        token="token",
        current_run_id=999,
        window_hours=24,
        now=now,
        opener=lambda request, timeout=0: _FakeResponse(runs),
    )

    assert decision.skip_suite is False
    assert decision.candidate_tree == merge_tree
    assert decision.reason == "no_matching_tree"


def test_decide_reuse_fails_open_on_api_errors(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    decision = probe.decide_reuse(
        worktree=repo,
        api_url="https://api.github.com",
        repository="upyoke/yoke",
        token="token",
        current_run_id=1,
        opener=lambda request, timeout=0: (_ for _ in ()).throw(URLError("boom")),
    )

    assert decision.skip_suite is False
    assert decision.reason == "no_successful_runs"


def test_decide_reuse_ignores_runs_outside_window(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    now = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)
    stale = (now - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = {
        "workflow_runs": [
            {
                "id": 100,
                "event": "push",
                "head_sha": head,
                "created_at": stale,
                "html_url": "https://example.test/runs/100",
            }
        ]
    }

    decision = probe.decide_reuse(
        worktree=repo,
        api_url="https://api.github.com",
        repository="upyoke/yoke",
        token="token",
        current_run_id=999,
        window_hours=24,
        now=now,
        opener=lambda request, timeout=0: _FakeResponse(runs),
    )

    assert decision.skip_suite is False
    assert decision.reason == "no_matching_tree"


def test_main_writes_github_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    output = tmp_path / "github_output"
    summary = tmp_path / "summary.md"
    output.write_text("", encoding="utf-8")
    summary.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "upyoke/yoke")
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    def fake_decide(**kwargs: Any) -> probe.ReuseDecision:
        return probe.ReuseDecision(
            skip_suite=True,
            candidate_tree="abc",
            covering_run_id=44,
            covering_head_sha=head,
            covering_html_url="https://example.test/runs/44",
            reason="identical_tree",
        )

    monkeypatch.setattr(probe, "decide_reuse", fake_decide)
    assert probe.main(["--worktree", str(repo), "--write-github-output"]) == 0
    text = output.read_text(encoding="utf-8")
    assert "skip_suite=true" in text
    assert "covering_run_id=44" in text
    assert "identical_tree" in summary.read_text(encoding="utf-8")


def test_merge_group_candidate_reuses_its_entry_run(tmp_path: Path) -> None:
    """A solo train rebased onto the base builds the entry run's own tree."""
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "PRJ-9")
    (repo / "b.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", "lane")
    lane_head = _git(repo, "rev-parse", "HEAD")
    # The queue builds its candidate by merging the lane into the base it is
    # already sitting on, which fast-forwards to the very same tree.
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--ff-only", "PRJ-9")
    candidate_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    now = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)
    runs = {
        "workflow_runs": [
            {
                "id": 1077,
                "event": "pull_request",
                "head_sha": lane_head,
                "created_at": "2026-08-07T17:50:00Z",
                "html_url": "https://example.test/runs/1077",
            }
        ]
    }

    decision = probe.decide_reuse(
        worktree=repo,
        api_url="https://api.github.com",
        repository="upyoke/yoke",
        token="token",
        current_run_id=1078,
        window_hours=24,
        now=now,
        opener=lambda request, timeout=0: _FakeResponse(runs),
    )

    assert decision.skip_suite is True
    assert decision.candidate_tree == candidate_tree
    assert decision.covering_run_id == 1077
    assert decision.reason == "identical_tree"


def test_a_batch_train_tree_no_run_covers_runs_the_suite(tmp_path: Path) -> None:
    """Two lanes combine into a tree neither entry run ever tested."""
    repo = _init_repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    heads = []
    for name, filename in (("PRJ-9", "b.txt"), ("PRJ-10", "c.txt")):
        _git(repo, "checkout", "-b", name, base)
        (repo / filename).write_text(name, encoding="utf-8")
        _git(repo, "add", filename)
        _git(repo, "commit", "-m", name)
        heads.append(_git(repo, "rev-parse", "HEAD"))
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "PRJ-9", "PRJ-10", "-m", "train")
    now = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)
    runs = {
        "workflow_runs": [
            {
                "id": 1100 + index,
                "event": "pull_request",
                "head_sha": head,
                "created_at": "2026-08-07T17:50:00Z",
                "html_url": f"https://example.test/runs/{1100 + index}",
            }
            for index, head in enumerate(heads)
        ]
    }

    decision = probe.decide_reuse(
        worktree=repo,
        api_url="https://api.github.com",
        repository="upyoke/yoke",
        token="token",
        current_run_id=1200,
        window_hours=24,
        now=now,
        opener=lambda request, timeout=0: _FakeResponse(runs),
    )

    assert decision.skip_suite is False
    assert decision.reason == "no_matching_tree"


def test_commit_tree_via_api_reads_tree_sha() -> None:
    payload = {"tree": {"sha": "deadbeef" * 5}}

    assert (
        probe.commit_tree_via_api(
            api_url="https://api.github.com",
            repository="upyoke/yoke",
            token="token",
            commit_sha="abc123",
            opener=lambda request, timeout=0: _FakeResponse(payload),
        )
        == "deadbeef" * 5
    )


def test_decide_reuse_accepts_any_trigger_event(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    now = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)
    runs = {
        "workflow_runs": [{
            "id": 100, "event": "schedule", "head_sha": head,
            "created_at": "2026-08-07T17:00:00Z",
            "html_url": "https://example.test/runs/100",
        }]
    }
    decision = probe.decide_reuse(
        worktree=repo, api_url="https://api.github.com",
        repository="upyoke/yoke", token="token", current_run_id=999,
        window_hours=24, now=now,
        opener=lambda request, timeout=0: _FakeResponse(runs),
    )
    assert decision.skip_suite is True
    assert decision.covering_run_id == 100
