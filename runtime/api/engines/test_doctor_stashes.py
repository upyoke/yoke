"""Tests for the doctor engine's stash health check.

A stash is not part of any lane: it lives in the repository's shared ref
namespace, so it outlives the worktree it was taken in and is reported on
its own terms.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_orphaned_stashes,
)


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
