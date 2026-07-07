"""Divergence handling, post-merge checkout, and post-merge cleanup tests.

Shared fixtures and helpers live in test_merge_worktree_full.py.
"""

import subprocess

import pytest

from runtime.api.test_merge_worktree_full import (
    TEST_BRANCH,
    MergeEnv,
    _git,
    _write_file,
    merge_env,  # re-export so pytest recognises this fixture in the child module  # noqa: F401
    run_merge,
)


# ===========================================================================
# Tests: Divergence handling
# ===========================================================================
class TestDivergenceHandling:
    """Generated-files-only divergence auto-resolves."""

    def test_yok602_board_only_divergence(self, merge_env: MergeEnv) -> None:
        """BOARD.md-only divergence merges cleanly."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature regen)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "chore: regenerate board")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / ".yoke" / "BOARD.md", "# Board (main regen)\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md")
        _git(repo, "commit", "-m", "chore: board update on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0

        assert (
            "auto-resolve" in result.stdout.lower()
            or "skipping empty rebase commit" in result.stdout
            or "merge-commit succeeded" in result.stdout.lower()
        )

    def test_yok602_genfiles_only_divergence(self, merge_env: MergeEnv) -> None:
        """Generated files-only divergence merges cleanly."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature)\n")
        _write_file(wt / ".yoke" / "BOARD.md.ts", "export const board = 'feature';\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md", ".yoke/BOARD.md.ts")
        _git(wt, "commit", "-m", "chore: regen board artifacts")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / ".yoke" / "BOARD.md", "# Board (main)\n")
        _write_file(repo / ".yoke" / "BOARD.md.ts", "export const board = 'main';\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md", ".yoke/BOARD.md.ts")
        _git(repo, "commit", "-m", "chore: board artifact update on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0

        # Python engine may resolve in pre-merge integration or main merge
        assert (
            "auto-resolve" in result.stdout.lower()
            or "merge-commit succeeded" in result.stdout.lower()
        )

    def test_yok602_multi_commit_board_empty(self, merge_env: MergeEnv) -> None:
        """Multi-commit with BOARD.md changes merges cleanly."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature v1)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "chore: board regen v1")
        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature v2)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "chore: board regen v2")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / ".yoke" / "BOARD.md", "# Board (main v1)\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md")
        _git(repo, "commit", "-m", "chore: board update on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0


# ===========================================================================
# Tests: Post-merge checkout
# ===========================================================================
class TestPostMergeCheckout:
    """Repo ends on target branch after merge."""

    def test_yok858_target_branch_checkout(self, merge_env: MergeEnv) -> None:
        """Repo on main after merge."""
        result = run_merge(merge_env)
        assert result.exit_code == 0

        head = _git(merge_env.repo, "rev-parse", "--abbrev-ref", "HEAD", check=False)
        assert head.stdout.strip() == "main"

    def test_yok858_non_target_corrected(self, merge_env: MergeEnv) -> None:
        """Non-target branch corrected, YOKE_REPO_ROOT in output."""
        result = run_merge(merge_env)
        assert result.exit_code == 0

        head = _git(merge_env.repo, "rev-parse", "--abbrev-ref", "HEAD", check=False)
        assert head.stdout.strip() == "main"
        assert "YOKE_REPO_ROOT=" in result.stdout


# ===========================================================================
# Tests: post-merge cleanup exit-code class (exit 5)
# ===========================================================================
class TestYok1380PostMergeCleanup:
    """AC-5, AC-6, AC-8: when the git/PR merge has already
    committed on the target branch but post-merge view regeneration
    fails, the engine must return exit code 5 (not 1) and emit a
    precise ``MergeEngineFailed`` event with ``phase=post_merge_cleanup``
    and ``merge_committed=true`` so usher can skip the rollback path."""

    def test_exit_0_clean_path_still_works(self, merge_env: MergeEnv) -> None:
        """AC-8 (a): the happy path — merge + schema refresh + view
        regen + board rebuild all succeed — still returns 0 and prints
        the ``YOKE_REPO_ROOT={path}`` contract line last."""
        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "Regenerating DB-sourced views" in result.stdout
        assert f"YOKE_REPO_ROOT={merge_env.repo}" in result.stdout
        assert not (merge_env.repo / "data" / "config").exists()
        assert (merge_env.repo / ".yoke" / "BOARD.md").is_file()

    def test_exit_5_on_post_merge_cleanup_failure(
        self, merge_env: MergeEnv
    ) -> None:
        """AC-5/AC-6/AC-8 (b): forced post-merge cleanup failure returns
        exit 5 after the merge commit already exists on the target
        branch, and the precise MergeEngineFailed event carries
        ``phase=post_merge_cleanup`` + ``merge_committed=true``."""
        result = run_merge(
            merge_env,
            extra_env={"YOKE_MERGE_TEST_FORCE_REGEN_FAILURE": "1"},
        )

        # Exit 5, not 1 — this is the whole point of.
        assert result.exit_code == 5, (
            f"expected exit 5, got {result.exit_code}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        # The merge itself landed: 'Successfully merged' appears BEFORE
        # the cleanup failure banner.
        assert "Successfully merged" in result.stdout
        # And the merge commit really exists on the target branch.
        branch_log = _git(merge_env.repo, "log", "main", "--oneline", check=False)
        assert "feature work" in branch_log.stdout

        # Operator-facing guidance is present on stderr.
        assert "post-merge view regeneration failed" in result.stderr
        assert "do NOT roll the item back" in result.stderr
        assert "Recovery:" in result.stderr
        assert "/yoke usher" in result.stderr

        # The YOKE_REPO_ROOT output contract still appears so
        # done_transition can re-locate the Yoke repo (exit-5 path
        # must not break the stdout contract).
        assert f"YOKE_REPO_ROOT={merge_env.repo}" in result.stdout

        # The precise MergeEngineFailed event landed in the events
        # ledger with structured phase info.
        from runtime.api.fixtures.file_test_db import connect_test_db

        conn = connect_test_db(str(merge_env.db_path))
        try:
            rows = conn.execute(
                "SELECT envelope FROM events WHERE event_name='MergeEngineFailed' "
                "ORDER BY id DESC"
            ).fetchall()
        finally:
            conn.close()

        assert rows, "no MergeEngineFailed event found in events ledger"

        import json as _json
        # Envelopes wrap the caller-supplied context dict under
        # ``context.detail``; top-level ``context`` carries framing
        # metadata added by the event emitter.
        post_merge_cleanup_details = []
        for (envelope_json,) in rows:
            try:
                envelope = _json.loads(envelope_json)
            except (TypeError, _json.JSONDecodeError):
                continue
            detail = (envelope.get("context") or {}).get("detail") or {}
            if detail.get("phase") == "post_merge_cleanup":
                post_merge_cleanup_details.append(detail)

        assert len(post_merge_cleanup_details) >= 1, (
            "expected at least one MergeEngineFailed event with "
            f"phase=post_merge_cleanup; found envelopes: {[r[0] for r in rows]}"
        )
        cleanup_detail = post_merge_cleanup_details[0]
        assert cleanup_detail.get("merge_committed") is True
        assert cleanup_detail.get("exit_code") == 5
        assert cleanup_detail.get("error_type") == "RuntimeError"
        assert "YOKE_MERGE_TEST_FORCE_REGEN_FAILURE" in cleanup_detail.get("error", "")
        assert cleanup_detail.get("branch") == TEST_BRANCH
        assert cleanup_detail.get("target") == "main"

        # The generic MergeEngineFailed emission from run()'s
        # finally block must be suppressed for exit 5 — only the
        # precise post-merge-cleanup event should appear, not a
        # generic ``exit_code=<n>`` event without a ``phase`` key.
        generic_failures = []
        for (envelope_json,) in rows:
            try:
                envelope = _json.loads(envelope_json)
            except (TypeError, _json.JSONDecodeError):
                continue
            detail = (envelope.get("context") or {}).get("detail") or {}
            if "phase" not in detail:
                generic_failures.append(detail)
        assert not generic_failures, (
            "generic MergeEngineFailed emission should be suppressed for "
            f"exit 5; found: {generic_failures}"
        )
