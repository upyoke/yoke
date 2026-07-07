"""Tests for yoke_core.domain.check_path_claim_coverage_at_commit."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import check_path_claim_coverage_at_commit as mod
from yoke_core.domain._test_check_path_claim_helpers import (
    conn,  # noqa: F401  # re-exported pytest fixture
    init_repo,
    make_ctx,
    seed_claim,
    stage_file,
)


# ---------------------------------------------------------------------------
# files_outside_coverage
# ---------------------------------------------------------------------------


class TestFilesOutsideCoverage:
    def test_exact_file_match(self):
        assert mod.files_outside_coverage(["a.py"], ["a.py"]) == []

    def test_directory_prefix_match(self):
        assert mod.files_outside_coverage(["src/a.py"], ["src/"]) == []

    def test_uncovered_file(self):
        assert mod.files_outside_coverage(["b.py"], ["a.py"]) == ["b.py"]

    def test_uncovered_dir(self):
        assert mod.files_outside_coverage(
            ["other/a.py"], ["src/"]
        ) == ["other/a.py"]

    def test_preserves_input_order(self):
        result = mod.files_outside_coverage(
            ["c", "a", "b", "d"], ["a", "d"],
        )
        assert result == ["c", "b"]

    def test_empty_inputs(self):
        assert mod.files_outside_coverage([], []) == []
        assert mod.files_outside_coverage(["a"], []) == ["a"]
        assert mod.files_outside_coverage([], ["a"]) == []


# ---------------------------------------------------------------------------
# find_active_claim_for_item
# ---------------------------------------------------------------------------


class TestFindActiveClaimForItem:
    def test_returns_active_when_present(self, conn):
        seed_claim(
            conn, claim_id=1, item_id=42, state="planned", paths=["a.py"],
        )
        seed_claim(
            conn, claim_id=2, item_id=42, state="active", paths=["b.py"],
        )
        result = mod.find_active_claim_for_item(conn, 42)
        assert result is not None
        assert result["state"] == "active"
        assert result["claim_id"] == 2
        assert result["declared_paths"] == ["b.py"]

    def test_falls_back_to_planned(self, conn):
        seed_claim(
            conn, claim_id=1, item_id=99, state="planned", paths=["x"],
        )
        result = mod.find_active_claim_for_item(conn, 99)
        assert result is not None
        assert result["state"] == "planned"

    def test_terminal_states_excluded(self, conn):
        seed_claim(
            conn, claim_id=1, item_id=7, state="released", paths=["a"],
        )
        seed_claim(
            conn, claim_id=2, item_id=7, state="cancelled", paths=["b"],
        )
        assert mod.find_active_claim_for_item(conn, 7) is None

    def test_no_claim_for_item(self, conn):
        assert mod.find_active_claim_for_item(conn, 100) is None


# ---------------------------------------------------------------------------
# Suppression token + commit message
# ---------------------------------------------------------------------------


class TestSuppression:
    def test_token_in_message(self):
        assert mod.has_suppression_token(
            "fix something\n\n[no-path-claim-check]\n"
        )

    def test_no_token(self):
        assert not mod.has_suppression_token("clean commit message")

    def test_empty(self):
        assert not mod.has_suppression_token("")

    def test_none_safe(self):
        assert not mod.has_suppression_token(None)  # type: ignore[arg-type]


class TestReadCommitMessage:
    def test_reads_existing_message(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "COMMIT_EDITMSG").write_text("hello\n", encoding="utf-8")
        assert mod.read_commit_message(tmp_path) == "hello\n"

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert mod.read_commit_message(tmp_path) == ""

    def test_reads_message_in_linked_worktree(self, tmp_path: Path):
        wt_git = tmp_path / "main" / ".git" / "worktrees" / "feature"
        wt_git.mkdir(parents=True)
        (wt_git / "COMMIT_EDITMSG").write_text(
            "fix\n\n[no-path-claim-check]\n", encoding="utf-8",
        )
        wt_root = tmp_path / "worktrees" / "feature"
        wt_root.mkdir(parents=True)
        (wt_root / ".git").write_text(f"gitdir: {wt_git}\n", encoding="utf-8")
        assert mod._resolve_git_dir(wt_root) == wt_git
        assert mod.read_commit_message(wt_root) == "fix\n\n[no-path-claim-check]\n"

    def test_reads_message_in_linked_worktree_relative_gitdir(self, tmp_path: Path):
        wt_git = tmp_path / "main" / ".git" / "worktrees" / "feature"
        wt_git.mkdir(parents=True)
        (wt_git / "COMMIT_EDITMSG").write_text("rel\n", encoding="utf-8")
        wt_root = tmp_path / "worktrees" / "feature"
        wt_root.mkdir(parents=True)
        (wt_root / ".git").write_text(
            "gitdir: ../../main/.git/worktrees/feature\n", encoding="utf-8",
        )
        assert mod._resolve_git_dir(wt_root) == wt_git.resolve()
        assert mod.read_commit_message(wt_root) == "rel\n"

    def test_malformed_gitdir_file_returns_empty(self, tmp_path: Path):
        (tmp_path / ".git").write_text("garbage\n", encoding="utf-8")
        assert mod.read_commit_message(tmp_path) == ""


# ---------------------------------------------------------------------------
# format_deny
# ---------------------------------------------------------------------------


class TestFormatDeny:
    def test_lists_missing_paths(self):
        text = mod.format_deny(
            item_id=42,
            claim_id=7,
            missing_paths=["a.py", "b.py"],
            declared_paths=["src/"],
        )
        assert "a.py" in text
        assert "b.py" in text
        assert "src/" in text
        assert "YOK-42" in text

    def test_includes_widen_template(self):
        text = mod.format_deny(
            item_id=1,
            claim_id=99,
            missing_paths=["new.py", "extra.py"],
            declared_paths=[],
        )
        assert "path-claims widen" in text
        assert " 99 " in text  # positional claim_id
        assert "--paths 'new.py,extra.py'" in text
        assert "--reason" in text

    def test_mentions_suppression_token_and_no_verify(self):
        text = mod.format_deny(
            item_id=1, claim_id=1,
            missing_paths=["x"], declared_paths=["y"],
        )
        assert "[no-path-claim-check]" in text
        assert "--no-verify" in text


# ---------------------------------------------------------------------------
# staged_files
# ---------------------------------------------------------------------------


class TestStagedFiles:
    def test_returns_staged_paths(self, tmp_path: Path):
        init_repo(tmp_path)
        stage_file(tmp_path, "a.py")
        stage_file(tmp_path, "src/b.py")
        result = mod.staged_files(tmp_path)
        assert sorted(result) == ["a.py", "src/b.py"]

    def test_empty_when_nothing_staged(self, tmp_path: Path):
        init_repo(tmp_path)
        assert mod.staged_files(tmp_path) == []

    def test_non_repo_returns_empty(self, tmp_path: Path):
        assert mod.staged_files(tmp_path) == []


# ---------------------------------------------------------------------------
# _decide — pure decision body
# ---------------------------------------------------------------------------


class TestDecide:
    def test_no_op_outside_worktree(
        self, conn, tmp_path: Path,
    ):
        ctx = make_ctx(item_id=42, inside=False)
        rc, msg = mod._decide(
            ctx=ctx, repo_root=tmp_path, conn=conn, commit_message="",
        )
        assert rc == 0
        assert msg == ""

    def test_no_op_when_no_current_item(
        self, conn, tmp_path: Path,
    ):
        ctx = make_ctx(item_id=None, inside=True)
        rc, msg = mod._decide(
            ctx=ctx, repo_root=tmp_path, conn=conn, commit_message="",
        )
        assert rc == 0
        assert msg == ""

    def test_no_op_when_no_active_claim(
        self, conn, tmp_path: Path,
    ):
        ctx = make_ctx(item_id=42, inside=True)
        rc, msg = mod._decide(
            ctx=ctx, repo_root=tmp_path, conn=conn, commit_message="",
        )
        assert rc == 0
        assert msg == ""

    def test_no_op_when_no_staged_files(
        self, conn, tmp_path: Path,
    ):
        init_repo(tmp_path)
        seed_claim(
            conn, claim_id=1, item_id=42, state="active", paths=["a.py"],
        )
        ctx = make_ctx(item_id=42, inside=True)
        rc, msg = mod._decide(
            ctx=ctx, repo_root=tmp_path, conn=conn, commit_message="",
        )
        assert rc == 0
        assert msg == ""

    def test_pass_when_all_files_covered(
        self, conn, tmp_path: Path,
    ):
        init_repo(tmp_path)
        stage_file(tmp_path, "a.py")
        stage_file(tmp_path, "src/b.py")
        seed_claim(
            conn, claim_id=1, item_id=42, state="active",
            paths=["a.py", "src/"],
        )
        ctx = make_ctx(item_id=42, inside=True)
        rc, msg = mod._decide(
            ctx=ctx, repo_root=tmp_path, conn=conn, commit_message="",
        )
        assert rc == 0
        assert msg == ""

    def test_refuses_when_files_outside_coverage(
        self, conn, tmp_path: Path,
    ):
        init_repo(tmp_path)
        stage_file(tmp_path, "a.py")
        stage_file(tmp_path, "extra.py")
        seed_claim(
            conn, claim_id=7, item_id=42, state="active", paths=["a.py"],
        )
        ctx = make_ctx(item_id=42, inside=True)
        rc, msg = mod._decide(
            ctx=ctx, repo_root=tmp_path, conn=conn,
            commit_message="not the suppression token",
        )
        assert rc == 1
        assert "extra.py" in msg
        assert "path-claims widen" in msg
        assert " 7 " in msg  # positional claim_id

    def test_suppression_token_allows_commit(
        self, conn, tmp_path: Path,
    ):
        init_repo(tmp_path)
        stage_file(tmp_path, "extra.py")
        seed_claim(
            conn, claim_id=7, item_id=42, state="active", paths=["a.py"],
        )
        ctx = make_ctx(item_id=42, inside=True)
        with mock.patch(
            "yoke_core.domain.events.emit_event",
        ) as emit:
            rc, msg = mod._decide(
                ctx=ctx, repo_root=tmp_path, conn=conn,
                commit_message="cleanup\n\n[no-path-claim-check]\n",
            )
        assert rc == 0
        assert msg == ""
        assert emit.called
        kwargs = emit.call_args.kwargs
        assert "PathClaimCoverageSuppressed" in emit.call_args.args
        assert kwargs["context"]["claim_id"] == 7
        assert "extra.py" in kwargs["context"]["missing_paths"]


# ---------------------------------------------------------------------------
# main() — outside-worktree no-op without DB
# ---------------------------------------------------------------------------


class TestMainOutsideWorktree:
    def test_main_returns_zero_on_main(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        init_repo(tmp_path)
        monkeypatch.chdir(tmp_path)
        for var in (
            "YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID",
        ):
            monkeypatch.delenv(var, raising=False)
        assert mod.main([]) == 0

    def test_main_returns_zero_with_unresolved_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        init_repo(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("YOKE_SESSION_ID", "ghost")
        assert mod.main([]) == 0
