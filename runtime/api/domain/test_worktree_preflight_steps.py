"""Unit tests for worktree_preflight step helpers."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from yoke_core.domain import worktree_preflight_steps as steps


def _fake_run_factory(canned):
    """Return a callable that pops responses off a queue.

    ``canned`` is a list of (returncode, stdout, stderr) tuples returned
    in FIFO order. Lets tests script the underlying ``_run`` calls
    without exec'ing real subprocesses.
    """
    queue = list(canned)

    def _fake_run(cmd, *_args, **_kwargs):
        if not queue:
            raise AssertionError(f"unexpected _run call: {cmd!r}")
        rc, out, err = queue.pop(0)
        return SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    return _fake_run, queue


class TestPhysicalCwdMode:
    def test_matched_when_cwd_equals_worktree(self, tmp_path):
        assert steps.physical_cwd_mode(str(tmp_path), str(tmp_path)) == steps.CWD_MODE_MATCHED

    def test_matched_when_cwd_inside_worktree(self, tmp_path):
        sub = tmp_path / "runtime" / "api"
        sub.mkdir(parents=True)
        assert steps.physical_cwd_mode(str(sub), str(tmp_path)) == steps.CWD_MODE_MATCHED

    def test_static_when_cwd_outside_worktree(self, tmp_path):
        wt = tmp_path / ".worktrees" / "YOK-1"
        wt.mkdir(parents=True)
        assert steps.physical_cwd_mode(str(tmp_path), str(wt)) == steps.CWD_MODE_STATIC

    def test_static_when_cwd_is_sibling(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert steps.physical_cwd_mode(str(a), str(b)) == steps.CWD_MODE_STATIC


class TestSanctionedPatternsRetired:
    """sanctioned_patterns() retired with the envelope; assert the symbol is gone."""

    def test_sanctioned_patterns_no_longer_exported(self):
        assert not hasattr(steps, "sanctioned_patterns")


class TestCheckDirtyMain:
    def test_clean_main_returns_no_block(self, monkeypatch):
        canned = [
            (0, "", ""),  # diff --name-only
            (0, "", ""),  # diff --name-only --cached
            (0, "", ""),  # ls-files --others --exclude-standard
        ]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(steps, "_run", fake_run)
        blocked, kind, paths = steps.check_dirty_main("/repo")
        assert blocked is False
        assert (kind, paths) == ("", [])

    def test_tracked_dirt_blocks_with_paths(self, monkeypatch):
        canned = [
            (0, "runtime/api/foo.py\n", ""),
            (0, "", ""),
            (0, "", ""),
        ]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(steps, "_run", fake_run)
        blocked, kind, paths = steps.check_dirty_main("/repo")
        assert blocked is True
        assert kind == steps.BLOCK_DIRTY_TRACKED
        assert "runtime/api/foo.py" in paths

    def test_staged_dirt_also_blocks_as_tracked(self, monkeypatch):
        canned = [
            (0, "", ""),
            (0, "runtime/api/bar.py\n", ""),
            (0, "", ""),
        ]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(steps, "_run", fake_run)
        blocked, kind, paths = steps.check_dirty_main("/repo")
        assert blocked is True
        assert kind == steps.BLOCK_DIRTY_TRACKED
        assert paths == ["runtime/api/bar.py"]

    def test_untracked_blocks_only_when_no_tracked_dirt(self, monkeypatch):
        canned = [
            (0, "", ""),
            (0, "", ""),
            (0, "scratch.txt\n", ""),
        ]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(steps, "_run", fake_run)
        blocked, kind, paths = steps.check_dirty_main("/repo")
        assert blocked is True
        assert kind == steps.BLOCK_DIRTY_UNTRACKED
        assert paths == ["scratch.txt"]


class TestActivatePathClaims:
    def test_success_with_activated_ids(self, monkeypatch):
        canned = [(0, "activated=[39, 40]\n", "")]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(steps, "_run", fake_run)
        ok, err, ids = steps.activate_path_claims(1599)
        assert ok is True
        assert err == ""
        assert ids == [39, 40]

    def test_blocked_returns_stderr(self, monkeypatch):
        canned = [(1, "", "BLOCKED: claim 39 is blocked: serial-via-dependency\n")]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(steps, "_run", fake_run)
        ok, err, ids = steps.activate_path_claims(1599)
        assert ok is False
        assert "BLOCKED" in err
        assert ids == []

    def test_malformed_activated_line_does_not_crash(self, monkeypatch):
        canned = [(0, "activated=not-json\n", "")]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(steps, "_run", fake_run)
        ok, err, ids = steps.activate_path_claims(1599)
        assert ok is True
        assert ids == []


class TestClaimWork:
    def test_already_owned_treated_as_success(self, monkeypatch):
        canned = [(0, '{"success": true, "claim": "(already owned)"}\n', "")]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(steps, "_run", fake_run)
        ok, msg = steps.claim_work(1599)
        assert ok is True
        assert "already" in msg.lower()

    def test_other_session_holding_returns_failure(self, monkeypatch):
        canned = [(2, "", "already claimed by session 'alt'\n")]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(steps, "_run", fake_run)
        ok, msg = steps.claim_work(1599)
        assert ok is False
        assert "already claimed by session" in msg
