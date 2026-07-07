"""Regression coverage for ``.worktrees/YOK-*`` pollution detection.

Exercises the snapshot + check helpers underlying the session-scoped
autouse pollution-check fixture. Each test plants a decoy directory in
a ``tmp_path`` repo root, drives the helpers, and tears the decoy down
in ``finally`` regardless of outcome — the tempdir itself is auto-cleaned
by pytest.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures import runtime as fixtures_runtime


def _make_fake_repo(tmp_path):
    (tmp_path / ".worktrees").mkdir()
    return tmp_path


def test_pollution_check_fires_on_decoy_worktree(tmp_path):
    repo = _make_fake_repo(tmp_path)
    baseline = fixtures_runtime._capture_pollution_baseline(repo)
    decoy = repo / ".worktrees" / "YOK-99999"
    decoy.mkdir()
    try:
        with pytest.raises(pytest.fail.Exception) as exc_info:
            fixtures_runtime._check_pollution_against_baseline(baseline)
        message = str(exc_info.value)
        assert "YOK-99999" in message
        assert ".worktrees/YOK-*" in message
        assert str(decoy) in message
    finally:
        if decoy.exists():
            decoy.rmdir()


def test_pollution_check_stays_silent_when_clean(tmp_path):
    repo = _make_fake_repo(tmp_path)
    baseline = fixtures_runtime._capture_pollution_baseline(repo)
    fixtures_runtime._check_pollution_against_baseline(baseline)


def test_pollution_check_ignores_preexisting_worktrees(tmp_path):
    """A `YOK-*` entry that exists in the pre-snapshot must not be reported."""
    repo = _make_fake_repo(tmp_path)
    inherited = repo / ".worktrees" / "YOK-99997"
    inherited.mkdir()
    try:
        baseline = fixtures_runtime._capture_pollution_baseline(repo)
        fixtures_runtime._check_pollution_against_baseline(baseline)
    finally:
        inherited.rmdir()


def test_pollution_check_reports_sibling_state_residue(tmp_path):
    repo = _make_fake_repo(tmp_path)
    baseline = fixtures_runtime._capture_pollution_baseline(repo)
    residue = repo / "yoke"
    residue.mkdir()
    try:
        with pytest.raises(pytest.fail.Exception) as exc_info:
            fixtures_runtime._check_pollution_against_baseline(baseline)
        assert str(residue) in str(exc_info.value)
        assert "Stray sibling-state residue" in str(exc_info.value)
    finally:
        residue.rmdir()


def test_snapshot_worktree_dirs_returns_only_sun_prefixed(tmp_path):
    (tmp_path / ".worktrees").mkdir()
    (tmp_path / ".worktrees" / "YOK-1").mkdir()
    (tmp_path / ".worktrees" / "YOK-42").mkdir()
    (tmp_path / ".worktrees" / "scratch").mkdir()

    snapshot = fixtures_runtime._snapshot_worktree_dirs(tmp_path)
    assert snapshot == {"YOK-1", "YOK-42"}


def test_snapshot_worktree_dirs_returns_empty_when_dir_missing(tmp_path):
    assert fixtures_runtime._snapshot_worktree_dirs(tmp_path) == set()
