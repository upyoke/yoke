"""
test_merge_worktree_execute.py — Basic merge correctness, rebase strategy,
trial merge, and merge-commit detection tests for the merge-worktree engine.

Conflict resolution tests live in ``test_merge_worktree_conflict.py``;
additive conflict tests live in ``test_merge_worktree_additive.py``;
fail-fast / existing-PR-reuse / freshness-race tests live in
``test_merge_worktree_failfast.py``.

Shared fixtures and helpers live in ``test_merge_worktree_full.py``.
"""

import json

from runtime.api.merge_worktree_full_test_support import (
    TEST_BRANCH,
    MergeEnv,
    _git,
    _write_file,
    merge_env as merge_env,
    run_merge,
)


# ===========================================================================
# Tests: Basic merge behavior
# ===========================================================================
class TestBasicMerge:
    """Bug A1, A3, A4 — fundamental merge correctness."""

    def test_bug_a1_dirty_current_plan(self, merge_env: MergeEnv) -> None:
        """Dirty BOARD.md (gitignored) does not block merge."""
        _write_file(merge_env.repo / ".yoke" / "BOARD.md", "dirty board content\n")
        result = run_merge(merge_env)
        assert result.exit_code == 0

        # BOARD.md is gitignored — invisible to git
        diff = _git(merge_env.repo, "diff", "--name-only", check=False)
        assert ".yoke/BOARD.md" not in diff.stdout

    def test_clean_merge_preserves_lane_and_reports_all_steps(self, merge_env: MergeEnv) -> None:
        """The happy-path merge flow (PR create → CI → merge) completes
        cleanly with the seeded REST fakes from the fixture."""
        result = run_merge(merge_env)
        assert result.exit_code == 0
        # Successful merge surfaces the verification + success lines.
        assert "Successfully merged" in result.stdout
        assert "Falling back to merge-commit" not in result.stdout
        assert "Running trial merge" in result.stdout
        assert "Trial merge clean" in result.stdout
        assert "Running pre-flight checks" in result.stdout
        assert "Pre-flight checks passed" in result.stdout
        assert "up to date" in result.stdout or "matches origin" in result.stdout
        assert f"YOKE_REPO_ROOT={merge_env.repo}" in result.stdout
        assert not (merge_env.repo / "data" / "config").exists()
        assert _git(merge_env.repo, "branch", "--show-current").stdout.strip() == "main"
        assert str(merge_env.worktree) in _git(merge_env.repo, "worktree", "list", "--porcelain").stdout
        assert TEST_BRANCH in _git(merge_env.repo, "branch", "--list", TEST_BRANCH).stdout
        candidate = _git(merge_env.worktree, "rev-parse", "HEAD").stdout.strip()
        assert _git(merge_env.repo, "merge-base", "--is-ancestor", candidate, "origin/main").returncode == 0
        assert TEST_BRANCH in _git(merge_env.repo, "ls-remote", "--heads", str(merge_env.origin), TEST_BRANCH).stdout
        assert "Deleted remote branch" not in result.stdout
        assert "Regenerating DB-sourced views" not in result.stdout
        assert (merge_env.repo / ".yoke" / "BOARD.md").read_text() == "# Board\n"


# ===========================================================================
# Tests: Rebase strategy
# ===========================================================================
class TestRebaseStrategy:
    """Rebase with auto-resolve and merge-commit fallback."""


    def test_yok207_threshold_triggers_fallback(self, merge_env: MergeEnv) -> None:
        """Threshold=1 triggers fallback, merge succeeds."""
        repo = merge_env.repo
        wt = merge_env.worktree

        machine_config = merge_env.tmpdir / "machine-config.json"
        machine_config.write_text(
            json.dumps(
                {"schema_version": 1, "settings": {"merge_conflict_threshold": "1"}}
            ),
            encoding="utf-8",
        )

        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature v1)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "modify board on feature v1")
        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature v2)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "modify board on feature v2")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / ".yoke" / "BOARD.md", "# Board (main v1)\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md")
        _git(repo, "commit", "-m", "update board on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(
            merge_env,
            extra_env={"YOKE_MACHINE_CONFIG_FILE": str(machine_config)},
        )
        assert result.exit_code == 0


# ===========================================================================
# Tests: Trial merge
# ===========================================================================
class TestTrialMerge:
    """Trial merge for early conflict detection."""


    def test_yok208_trial_merge_conflict(self, merge_env: MergeEnv) -> None:
        """Non-auto-resolvable conflict detected by trial merge."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(repo / "shared-code.js", "main version\n")
        _git(repo, "add", "shared-code.js")
        _git(repo, "commit", "-m", "add shared code on main")
        _git(repo, "push", "origin", "main")

        _write_file(wt / "shared-code.js", "feature version\n")
        _git(wt, "add", "shared-code.js")
        _git(wt, "commit", "-m", "modify shared code on feature")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / "shared-code.js", "main updated version\n")
        _git(repo, "add", "shared-code.js")
        _git(repo, "commit", "-m", "update shared code on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 3
        assert "agent resolution" in result.stderr
        assert "real branch is untouched" in result.stderr

        # Trial branch cleaned up
        branch_list = _git(wt, "branch", "--list", f"trial/{TEST_BRANCH}", check=False)
        assert f"trial/{TEST_BRANCH}" not in branch_list.stdout.strip()

    def test_yok208_trial_merge_auto_resolvable(self, merge_env: MergeEnv) -> None:
        """Auto-resolvable (yoke-gen only) conflict passes trial."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "modify board on feature")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / ".yoke" / "BOARD.md", "# Board (main)\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md")
        _git(repo, "commit", "-m", "update board on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "Trial merge clean" in result.stdout


# ===========================================================================
# Tests: Merge commit detection
# ===========================================================================
class TestMergeCommitDetection:
    """Merge commits skip rebase."""

    def test_yok616_merge_commits_skip_rebase(self, merge_env: MergeEnv) -> None:
        """Branch with merge commits skips rebase."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(wt / "feature.txt", "feature change\n")
        _git(wt, "add", "feature.txt")
        _git(wt, "commit", "-m", "modify file A on feature")

        # Main modifies different file
        _write_file(repo / "script.sh", "main change v1\n")
        _git(repo, "add", "script.sh")
        _git(repo, "commit", "-m", "modify file B on main v1")
        _git(repo, "push", "origin", "main")

        # Feature merges main (merge commit #1)
        _git(wt, "fetch", "origin")
        _git(wt, "merge", "origin/main", "--no-edit")

        # Main modifies again
        _write_file(repo / "script.sh", "main change v2\n")
        _git(repo, "add", "script.sh")
        _git(repo, "commit", "-m", "modify file B on main v2")
        _git(repo, "push", "origin", "main")

        # Feature merges main (merge commit #2)
        _git(wt, "fetch", "origin")
        _git(wt, "merge", "origin/main", "--no-edit")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "merge commit(s)" in result.stdout
        assert "skipping rebase" in result.stdout

        # Verify content preserved
        _git(repo, "checkout", "main", check=False)
        _git(repo, "pull", "origin", "main", check=False)
        feat_content = _git(
            repo, "show", "HEAD:feature.txt", check=False
        ).stdout.strip()
        assert feat_content == "feature change"
        script_content = _git(
            repo, "show", "HEAD:script.sh", check=False
        ).stdout.strip()
        assert script_content == "main change v2"

    def test_yok616_no_merge_commits_uses_rebase(self, merge_env: MergeEnv) -> None:
        """No merge commits uses rebase."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(wt / "feature.txt", "feature only\n")
        _git(wt, "add", "feature.txt")
        _git(wt, "commit", "-m", "feature only change")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / "main-only.txt", "main addition\n")
        _git(repo, "add", "main-only.txt")
        _git(repo, "commit", "-m", "add main-only file")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0
