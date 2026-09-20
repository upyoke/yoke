"""Tests for the doctor engine's stash health check.

A stash is not part of any lane: it lives in the repository's shared ref
namespace, so it outlives the worktree it was taken in and is reported on
its own terms.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

from yoke_core.engines import doctor_report
from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_orphaned_stashes,
)

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
}


def _run(stdout: str) -> RecordCollector:
    """Run the check over one ``git stash list`` output.

    The check reads git and never the database, so nothing stands in for a
    connection.
    """
    rec = RecordCollector()
    with patch("yoke_core.engines.doctor_report._run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout, "")
        hc_orphaned_stashes(None, DoctorArgs(), rec)
    return rec


def test_no_stashes_passes():
    assert _run("").results[0].result == "PASS"


def test_a_yoke_safety_stash_warns():
    rec = _run("stash@{0} | 2026-09-19 | On main: yoke-pre-rebase-YOK-9999\n")

    assert rec.results[0].result == "WARN"
    assert "yoke-pre-rebase-" in rec.results[0].detail


def test_a_hand_parked_stash_warns():
    """The stash nothing owns is the one that must not be invisible.

    Only the merge path's own ``yoke-pre-rebase-`` stash is ever dropped
    automatically, so a stash parked by hand has no owner at all. Matching
    that prefix hid exactly the entries with nobody coming for them.
    """
    rec = _run("stash@{0} | 2026-09-19 | On YOK-1: park stray untracked file\n")

    assert rec.results[0].result == "WARN"
    assert "park stray untracked file" in rec.results[0].detail


def test_the_report_dates_each_stash_and_names_the_recovery():
    rec = _run("stash@{0} | 2026-09-19 | On main: WIP on feature\n")

    assert "2026-09-19" in rec.results[0].detail
    assert "git stash show -p" in rec.results[0].detail
    assert "git stash drop" in rec.results[0].detail


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )


def _park_two_same_day_stashes(tmp_path: Path) -> Path:
    repo = tmp_path / "stash-repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    tracked = repo / "tracked.txt"
    tracked.write_text("base\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "base")
    tracked.write_text("first\n")
    _git(repo, "stash", "push", "-m", "first-park")
    tracked.write_text("second\n")
    _git(repo, "stash", "push", "-m", "second-park")
    return repo


def _check_against_repo(repo: Path) -> RecordCollector:
    rec = RecordCollector()
    real_run = doctor_report._run

    def run_in_repo(cmd, cwd=None, timeout=30, env=None):
        return real_run(cmd, cwd=str(repo), timeout=timeout, env=env or _GIT_ENV)

    with patch("yoke_core.engines.doctor_report._run", side_effect=run_in_repo):
        hc_orphaned_stashes(None, DoctorArgs(), rec)
    return rec


def test_two_same_day_stashes_warn_with_distinct_numeric_selectors(tmp_path):
    """Same-day stashes must each carry a droppable ``stash@{N}``.

    A single-stash fixture cannot catch the defect: ``--date=short``
    rewrites ``%gd`` to the calendar day, so two stashes parked on one
    day print identically and ``git stash drop <ref>`` is ambiguous.
    """
    repo = _park_two_same_day_stashes(tmp_path)
    rec = _check_against_repo(repo)

    assert rec.results[0].result == "WARN"
    detail = rec.results[0].detail
    assert re.search(r"stash@\{\d{4}-\d{2}-\d{2}\}", detail) is None
    selectors = re.findall(r"^- (stash@\{\d+\})", detail, re.M)
    assert selectors == ["stash@{0}", "stash@{1}"]
    assert "first-park" in detail
    assert "second-park" in detail

    newer_hash = _git(repo, "rev-parse", selectors[0]).stdout.strip()
    older_hash = _git(repo, "rev-parse", selectors[1]).stdout.strip()
    assert newer_hash != older_hash

    _git(repo, "stash", "drop", selectors[1])
    remaining = _git(repo, "rev-parse", "stash@{0}").stdout.strip()
    assert remaining == newer_hash
    _git(repo, "stash", "drop", "stash@{0}")
    assert _git(repo, "stash", "list").stdout.strip() == ""
