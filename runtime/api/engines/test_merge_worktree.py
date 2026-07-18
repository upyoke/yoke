"""Tests for merge_worktree: arg parsing, validation, conflict classification.

Locks/preflight tests live in test_merge_worktree_locks.py.
View-rendering tests live in test_merge_worktree_views.py.
Sync-target tests live in test_merge_worktree_sync.py.

Pytest fixture (mw_db) shared via _merge_worktree_test_helpers (private module).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.engines import merge_worktree
from yoke_core.engines.merge_worktree import (
    MergeArgs,
    MergeContext,
    ConflictInfo,
    auto_resolve_conflicts,
    classify_conflict,
    is_additive_conflict,
    parse_args,
    validate_args,
)

from yoke_core.engines._merge_worktree_test_helpers import mw_db


class TestParseArgs:
    def test_branch_only(self):
        args = parse_args(["YOK-9999"])
        assert args.branch == "YOK-9999"
        assert args.target == "main"
        assert args.epic_ref is None
        assert args.local_merge is False

    def test_branch_and_target(self):
        args = parse_args(["YOK-9999", "develop"])
        assert args.branch == "YOK-9999"
        assert args.target == "develop"

    def test_all_positional(self):
        args = parse_args(["YOK-9999", "main", "YOK-100"])
        assert args.branch == "YOK-9999"
        assert args.target == "main"
        assert args.epic_ref == "YOK-100"

    def test_flags(self):
        args = parse_args(["--local", "--force-lock", "--keep-remote", "--skip-simulation", "YOK-9999"])
        assert args.local_merge is True
        assert args.force_lock is True
        assert args.keep_remote is True
        assert args.skip_simulation is True
        assert args.branch == "YOK-9999"

    def test_flags_after_positional(self):
        args = parse_args(["YOK-9999", "--local"])
        assert args.branch == "YOK-9999"
        assert args.local_merge is True


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidateArgs:
    def test_empty_branch(self):
        args = MergeArgs(branch="")
        err = validate_args(args)
        assert err is not None
        assert "Usage" in err

    def test_valid_branch(self):
        args = MergeArgs(branch="YOK-9999")
        err = validate_args(args)
        assert err is None

    def test_legacy_issue_branch(self):
        args = MergeArgs(branch="issue/YOK-9999")
        err = validate_args(args)
        assert err is not None
        assert "legacy" in err

    def test_legacy_epic_branch(self):
        args = MergeArgs(branch="epic/YOK-9999")
        err = validate_args(args)
        assert err is not None
        assert "legacy" in err


# ---------------------------------------------------------------------------
# Git runner tests
# ---------------------------------------------------------------------------


class TestRunGit:
    def test_sets_noninteractive_env_and_timeout(self, monkeypatch, tmp_path):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmd, 0, "ok", "")

        monkeypatch.setattr("subprocess.run", fake_run)
        monkeypatch.delenv("GIT_TERMINAL_PROMPT", raising=False)
        monkeypatch.delenv("GCM_INTERACTIVE", raising=False)
        monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
        monkeypatch.delenv("YOKE_GIT_COMMAND_TIMEOUT_SECONDS", raising=False)

        result = merge_worktree._run_git(
            ["status", "--short"],
            cwd=tmp_path,
            capture=True,
        )

        assert result.returncode == 0
        assert captured["cmd"] == ["git", "status", "--short"]
        assert captured["kwargs"]["cwd"] == str(tmp_path)
        assert captured["kwargs"]["capture_output"] is True
        assert captured["kwargs"]["text"] is True
        assert (
            captured["kwargs"]["timeout"]
            == merge_worktree._DEFAULT_GIT_COMMAND_TIMEOUT_SECONDS
        )
        assert captured["kwargs"]["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert captured["kwargs"]["env"]["GCM_INTERACTIVE"] == "Never"
        assert captured["kwargs"]["env"]["GIT_SSH_COMMAND"] == "ssh -oBatchMode=yes"

    def test_timeout_returns_failed_completed_process(self, monkeypatch, tmp_path):
        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd,
                kwargs["timeout"],
                output="partial stdout",
                stderr="partial stderr",
            )

        monkeypatch.setattr("subprocess.run", fake_run)
        monkeypatch.setenv("YOKE_GIT_COMMAND_TIMEOUT_SECONDS", "7")

        result = merge_worktree._run_git(
            ["push", "origin", "YOK-42"],
            cwd=tmp_path,
            capture=True,
        )

        assert result.returncode == merge_worktree._GIT_TIMEOUT_EXIT_CODE
        assert result.stdout == "partial stdout"
        assert "partial stderr" in result.stderr
        assert "timed out after 7s" in result.stderr
        assert "git push origin YOK-42" in result.stderr


# ---------------------------------------------------------------------------
# Conflict classification tests
# ---------------------------------------------------------------------------


class TestConflictClassification:
    def _make_ctx(self, **kwargs):
        args = MergeArgs(branch="YOK-9999")
        ctx = MergeContext(args=args, worktree_path="/tmp/test")
        for k, v in kwargs.items():
            setattr(ctx, k, v)
        return ctx

    def test_generated_file(self):
        ctx = self._make_ctx(generated_files=["dist/bundle.js"])
        info = classify_conflict("dist/bundle.js", ctx)
        assert info.classification == "generated (auto)"
        assert info.auto_resolvable is True

    def test_doc_file_not_branch_modified(self):
        ctx = self._make_ctx(branch_changed_files=[])
        info = classify_conflict("AGENTS.md", ctx)
        assert info.classification == "doc (auto)"
        assert info.auto_resolvable is True

    def test_doc_file_branch_modified(self):
        ctx = self._make_ctx(branch_changed_files=["AGENTS.md"])
        info = classify_conflict("AGENTS.md", ctx)
        assert info.classification == "doc (branch-modified, manual)"
        assert info.auto_resolvable is False

    def test_yoke_gen_file(self):
        ctx = self._make_ctx()
        info = classify_conflict(".yoke/BOARD.md.ts", ctx)
        assert info.classification == "yoke-gen (auto)"
        assert info.auto_resolvable is True

    def test_yoke_board(self):
        ctx = self._make_ctx()
        info = classify_conflict(".yoke/BOARD.md", ctx)
        assert info.classification == "yoke-gen (auto)"
        assert info.auto_resolvable is True

    def test_unknown_file(self):
        ctx = self._make_ctx()
        # Mock is_additive_conflict to return False
        with mock.patch.object(merge_worktree, "is_additive_conflict", return_value=False):
            info = classify_conflict("src/app.js", ctx)
        assert info.classification == "overlapping (needs agent judgement)"
        assert info.auto_resolvable is False

    def test_docs_glob(self):
        ctx = self._make_ctx(branch_changed_files=[])
        info = classify_conflict("docs/setup.md", ctx)
        assert info.classification == "doc (auto)"
        assert info.auto_resolvable is True


# ---------------------------------------------------------------------------
# Yoke-managed file classification tests
#
# merge_worktree.py imports the authoritative classifier from
# yoke_core.domain.classify_dirty_files. These tests exercise the re-exported
# symbol to guarantee the engine is wired to the single source of truth and
# that the managed/unmanaged split matches the domain contract documented in
# runtime/api/domain/classify_dirty_files.py.
# ---------------------------------------------------------------------------


class TestYokeManaged:
    def test_root_data_not_managed(self):
        assert merge_worktree.is_yoke_managed_pattern("data/orphan.md") is False

    def test_retired_projects_not_managed(self):
        assert (
            merge_worktree.is_yoke_managed_pattern("projects/externalwebapp/ops.sh")
            is False
        )

    def test_agents_scripts_managed(self):
        assert (
            merge_worktree.is_yoke_managed_pattern(
                ".agents/skills/yoke/scripts/some-helper.py"
            )
            is True
        )

    def test_simulation_report_managed(self):
        assert (
            merge_worktree.is_yoke_managed_pattern(
                "ouroboros/simulation-YOK-9999.md"
            )
            is True
        )

    def test_pad_managed(self):
        assert merge_worktree.is_yoke_managed_pattern(".yoke/strategy/PAD.md") is True

    def test_src_not_managed(self):
        assert merge_worktree.is_yoke_managed_pattern("src/app.js") is False

    def test_gitignored_views_not_managed(self):
        # Generated views are gitignored, so they never
        # appear in a dirty-state list.  The authoritative classifier
        # intentionally excludes them so that no code path can reintroduce
        # auto-staging for files that don't exist in the git tree.
        assert merge_worktree.is_yoke_managed_pattern(".yoke/BOARD.md") is False

    def test_engine_re_exports_domain_constant(self):
        # Guard against accidental re-introduction of a local constant that
        # could drift from yoke_core.domain.classify_dirty_files.
        from yoke_core.domain import classify_dirty_files as domain_cdf

        assert (
            merge_worktree.YOKE_MANAGED_PATTERNS
            is domain_cdf.YOKE_MANAGED_PATTERNS
        )
