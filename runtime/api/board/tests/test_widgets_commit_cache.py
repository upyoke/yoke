"""Tests for the unified per-commit cache.

Covers cold populate, warm memo hit, ``--no-walk`` incremental
populate, and per-day derivation across multiple repos.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date, timedelta

from yoke_contracts.board import widgets_commit_cache as cache_mod


def _init_repo_with_commits(repo_dir, commits: "list[tuple[str, str, str]]"):
    """*commits* is a list of (day, path, content) tuples."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.email", "t@t"], check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.name", "t"], check=True,
    )
    for i, (day, path, content) in enumerate(commits):
        f = repo_dir / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
        ts = f"{day}T12:00:00"
        env = {
            "GIT_AUTHOR_DATE": ts,
            "GIT_COMMITTER_DATE": ts,
            "PATH": os.environ.get("PATH", ""),
        }
        subprocess.run(
            ["git", "-C", str(repo_dir), "commit", "-q", "-m", f"c{i}"],
            check=True, env=env,
        )


class TestColdPopulate:
    def test_cold_populates_lines_strategy_and_count(self, tmp_path):
        repo = tmp_path / "repo"
        today = date.today()
        d1 = (today - timedelta(days=2)).isoformat()
        d2 = (today - timedelta(days=1)).isoformat()
        _init_repo_with_commits(repo, [
            (d1, "src/foo.py", "x = 1\n"),
            (d2, "strategy/plan.md", "title\nbody\n"),
        ])

        cache = cache_mod.get_commit_data([str(repo)])
        assert len(cache) == 2

        commits = cache_mod.commits_per_day([str(repo)], days=14)
        assert commits == {d1: 1, d2: 1}

        lines = cache_mod.lines_per_day([str(repo)], days=14)
        assert lines[d1] == 1
        assert lines[d2] == 2

        sml = cache_mod.strategy_lines_per_day([str(repo)], days=14)
        assert sml.get(d1, 0) == 0
        assert sml[d2] == 2

    def test_cold_populate_uses_generous_timeout(self, tmp_path, monkeypatch):
        # Cold path: cheap hash listing under the tight list timeout, then the
        # full --numstat walk under the generous bulk timeout. A from-empty
        # walk over a large repo legitimately takes seconds; the bulk bound
        # must exceed the warm bound so a slow cold walk is not silently
        # zeroed out of the cache.
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs.get("timeout")))
            if "--format=%H" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "abc123\n", "")
            return subprocess.CompletedProcess(
                cmd, 0, "COMMIT abc123 2026-06-04\n1\t0\ta.txt\n", "",
            )

        monkeypatch.setattr(cache_mod.subprocess, "run", fake_run)

        cache = cache_mod.get_commit_data([str(tmp_path / "repo")])

        assert cache["abc123"]["lines"] == 1
        assert [timeout for _, timeout in calls] == [
            cache_mod._LIST_TIMEOUT_SECONDS,
            cache_mod._BULK_POPULATE_TIMEOUT_SECONDS,
        ]
        assert (
            cache_mod._BULK_POPULATE_TIMEOUT_SECONDS
            > cache_mod._POPULATE_TIMEOUT_SECONDS
        )

    def test_warm_no_walk_uses_tight_timeout(self, tmp_path, monkeypatch):
        # Warm path: only the new commits since the last refresh, so the
        # --no-walk populate stays under the tight bound.
        monkeypatch.setattr(cache_mod, "_STALE_OK_SECONDS", 0)
        cache_path = tmp_path / "cache" / ".commit-cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        repo = str(tmp_path / "repo")
        # Seed an existing entry so the refresh takes the warm --no-walk branch.
        cache_path.write_text(
            '{"old111": {"day": "2026-06-01", "lines": 1, '
            f'"strategy_lines": 0, "repo": "{repo}"}}}}'
        )
        monkeypatch.setattr(cache_mod, "_cache_path", lambda: cache_path)
        cache_mod._reset_memo_for_tests()

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs.get("timeout")))
            if "--format=%H" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "old111\nnew222\n", "")
            return subprocess.CompletedProcess(
                cmd, 0, "COMMIT new222 2026-06-04\n1\t0\tb.txt\n", "",
            )

        monkeypatch.setattr(cache_mod.subprocess, "run", fake_run)

        cache_mod.get_commit_data([repo])

        # --no-walk populate (the second call) runs under the tight bound.
        assert [timeout for _, timeout in calls] == [
            cache_mod._LIST_TIMEOUT_SECONDS,
            cache_mod._POPULATE_TIMEOUT_SECONDS,
        ]


class TestWarmMemo:
    def test_second_call_hits_memo_no_subprocess(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        today = date.today()
        _init_repo_with_commits(repo, [(today.isoformat(), "a.txt", "v\n")])

        # Prime the memo.
        first = cache_mod.get_commit_data([str(repo)])
        assert first

        # Block subprocess to prove the second call doesn't hit git.
        def boom(*a, **kw):  # pragma: no cover - asserted not to run
            raise AssertionError("subprocess.run called on memoized path")
        monkeypatch.setattr(cache_mod.subprocess, "run", boom)

        second = cache_mod.get_commit_data([str(repo)])
        assert second is first

    def test_second_process_hits_stale_ok_file_cache(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        today = date.today().isoformat()
        _init_repo_with_commits(repo, [(today, "a.txt", "v\n")])

        first = cache_mod.get_commit_data([str(repo)])
        assert first
        cache_mod._reset_memo_for_tests()

        def boom(*a, **kw):  # pragma: no cover - asserted not to run
            raise AssertionError("subprocess.run called despite fresh file cache")

        monkeypatch.setattr(cache_mod.subprocess, "run", boom)
        second = cache_mod.get_commit_data([str(repo)])
        assert second
        assert second == first


class TestIncrementalNoWalk:
    def test_new_commit_uses_no_walk(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_mod, "_STALE_OK_SECONDS", 0)
        repo = tmp_path / "repo"
        today = date.today()
        d1 = (today - timedelta(days=1)).isoformat()
        _init_repo_with_commits(repo, [(d1, "a.txt", "v1\n")])

        # First call populates the cache via the bulk-walk path.
        cache_mod.get_commit_data([str(repo)])
        cache_mod._reset_memo_for_tests()

        # Add a new commit and refresh.
        f = repo / "b.txt"
        f.write_text("v2\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        ts = f"{today.isoformat()}T12:00:00"
        env = {
            "GIT_AUTHOR_DATE": ts,
            "GIT_COMMITTER_DATE": ts,
            "PATH": os.environ.get("PATH", ""),
        }
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "new"],
            check=True, env=env,
        )

        cache = cache_mod.get_commit_data([str(repo)])
        assert len(cache) == 2
        commits = cache_mod.commits_per_day([str(repo)], days=14)
        assert commits[today.isoformat()] == 1
        assert commits[d1] == 1


class TestMultiRepoFiltering:
    def test_per_day_filters_by_repo(self, tmp_path):
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        today = date.today().isoformat()
        _init_repo_with_commits(repo_a, [(today, "x.txt", "a\n")])
        _init_repo_with_commits(repo_b, [(today, "y.txt", "b\n")])

        # Populate the cache with both repos.
        cache_mod.get_commit_data([str(repo_a), str(repo_b)])

        # Slice to repo A only.
        a_only = cache_mod.commits_per_day([str(repo_a)], days=14)
        assert a_only == {today: 1}

        # Both.
        both = cache_mod.commits_per_day([str(repo_a), str(repo_b)], days=14)
        assert both == {today: 2}
