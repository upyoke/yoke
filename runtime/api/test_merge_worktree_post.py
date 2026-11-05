"""Post-merge dirty file handling, sync, remote cleanup, and cleanup-trap tests.

Divergence + post-merge checkout + post-merge cleanup tests
    → test_merge_worktree_post_diverge.py
Streaming primitive tests → test_merge_worktree_post_streaming.py
run_tests integration tests → test_merge_worktree_post_runtests.py

Shared fixtures and helpers live in test_merge_worktree_full.py.
"""

import subprocess
import sys
import textwrap
from unittest import mock

from yoke_core.engines import merge_worktree as engine
from yoke_core.engines import merge_worktree_cleanup as cleanup
from yoke_core.engines.merge_worktree_context import MergeArgs, MergeContext
from yoke_core.engines.remote_branch_cleanup import RemoteBranchDeleteResult

import pytest

from runtime.api.test_merge_worktree_full import (
    TEST_BRANCH,
    MergeEnv,
    MERGE_MODULE,
    WORKTREE_ROOT,
    _git,
    _write_file,
    merge_env as _shared_merge_env,
    run_merge,
)


@pytest.fixture(name="merge_env")
def _merge_env_fixture(tmp_path, request):
    """Expose the shared fixture without relying on plugin load order."""
    return _shared_merge_env.__wrapped__(tmp_path, request)


@pytest.fixture
def cleanup_context(tmp_path, monkeypatch):
    """A proven landing with local post-merge effects isolated."""
    from yoke_core.domain import merge_landing_proof
    from yoke_core.engines import merge_worktree_landing

    ctx = MergeContext(
        args=MergeArgs(branch="feature", standalone=True),
        repo_root=str(tmp_path), yoke_repo_root=str(tmp_path),
        worktree_path=str(tmp_path / "lane"),
    )
    monkeypatch.setattr(merge_landing_proof, "verified_target_sha", lambda *a: "b" * 40)
    monkeypatch.setattr(merge_worktree_landing, "record_worktree_landing", lambda *a, **k: True)
    monkeypatch.setattr(engine, "_run_git", mock.Mock(return_value=subprocess.CompletedProcess([], 0, "", "")))
    monkeypatch.setattr(engine, "_emit_merge_event", mock.Mock())
    monkeypatch.setattr(engine, "_sync_local_target", mock.Mock(return_value=True))
    monkeypatch.setattr(engine, "_schema_refresh", mock.Mock())
    monkeypatch.setattr(engine, "_ensure_target_branch", mock.Mock())
    return ctx


# ===========================================================================
# Tests: Post-merge dirty file handling
# ===========================================================================
class TestPostMergeDirty:
    """File dirtied during merge is stashed/restored."""

    def test_yok128_dirty_post_merge_rebase(self, merge_env: MergeEnv) -> None:
        """File dirtied during merge is stashed/restored.

        The dirty side-effect is now wired through the REST merge fake's
        ``side_effect`` shell hook (the legacy ``MOCK_GH_DIRTY_SCRIPT``
        achieved the same thing via the ``gh pr merge`` subprocess that
        the engine no longer calls).
        """
        from runtime.api import merge_worktree_test_rest_fakes as rest_fakes

        repo = merge_env.repo
        dirty_file = repo / "session-notes.txt"
        _write_file(dirty_file, "clean\n")
        _git(repo, "add", "session-notes.txt")
        _git(repo, "commit", "-m", "add session-notes")
        _git(repo, "push", "origin", "main")

        # Overlay the merge fake with a side-effect that runs the merge
        # AND dirties the file (chained after the happy-path merge that
        # the fixture seeded).
        merge_origin = rest_fakes._merge_side_effect_command(
            str(merge_env.origin), TEST_BRANCH
        )
        dirty_cmd = f"echo 'modified during merge' > '{dirty_file}'"
        rest_fakes._write(
            merge_env.rest_fake_dir,
            rest_fakes.pulls_merge_filename("9999"),
            body={"merged": True, "message": "Pull Request successfully merged"},
            side_effect=f"{merge_origin}; {dirty_cmd}",
        )

        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "Stashing dirty files before sync" in result.stdout
        assert "Restoring stashed files" in result.stdout

        content = dirty_file.read_text().strip()
        assert content == "modified during merge"

        stash = _git(repo, "stash", "list", check=False)
        assert "yoke-post-merge-sync" not in stash.stdout


# ===========================================================================
# Tests: Post-merge operations
# ===========================================================================
class TestPostMergeOps:
    """Post-merge sync, agent worktree pruning."""

    def test_yok443_post_merge_sync_pull_rebase(self, merge_env: MergeEnv) -> None:
        """Post-merge sync uses pull --rebase."""
        repo = merge_env.repo

        # Local bookkeeping commit not pushed
        _write_file(repo / ".yoke" / "BOARD.md", "bookkeeping update\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md")
        _git(repo, "commit", "-m", "bookkeeping: board update")
        # Do NOT push

        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "Syncing" in result.stdout or "up to date" in result.stdout

        # Local main includes origin/main
        _git(repo, "fetch", "origin", "main", check=False)
        anc = _git(
            repo, "merge-base", "--is-ancestor", "origin/main", "main", check=False
        )
        assert anc.returncode == 0

    def test_sync_failure_preserves_landed_lane_for_retry(
        self, cleanup_context, monkeypatch, capsys,
    ) -> None:
        """A proven landing with failed sync returns its distinct retry exit."""
        monkeypatch.setattr(engine, "_sync_local_target", mock.Mock(return_value=False))
        assert cleanup._post_merge_cleanup(cleanup_context, no_changes=False) == 5
        engine._sync_local_target.assert_called_once_with(cleanup_context)
        assert "merge_target_sync_failed: landing is proven" in capsys.readouterr().err
        engine._schema_refresh.assert_not_called()
        assert not any(call.args[0][:2] == ["worktree", "remove"]
                       for call in engine._run_git.call_args_list)

    def test_unowned_agent_residue_is_preserved(self, merge_env: MergeEnv) -> None:
        """Filesystem naming alone never authorizes destructive cleanup."""
        repo = merge_env.repo

        # Create stale agent worktree directory
        stale_dir = repo / ".claude" / "worktrees" / "agent-test-stale-12345"
        stale_dir.mkdir(parents=True, exist_ok=True)
        _write_file(stale_dir / "dummy.txt", "stale agent file\n")

        # Create stale agent branch
        _git(repo, "branch", "worktree-agent-stale-12345", check=False)

        result = run_merge(merge_env)
        assert result.exit_code == 0

        # No terminal DB owner, clean-status proof, or active-claim proof exists.
        assert stale_dir.exists()

        branch_list = _git(
            repo, "branch", "--list", "worktree-agent-stale-12345", check=False
        )
        assert "worktree-agent-stale-12345" in branch_list.stdout.strip()

        assert "Pruning stale agent worktree" not in result.stdout
        assert "Deleting orphaned agent branch" not in result.stdout

    def test_yok443_agent_worktree_excluded(self, merge_env: MergeEnv) -> None:
        """Non-agent worktrees excluded from dirty check."""
        repo = merge_env.repo
        agent_dir = repo / ".claude" / "worktrees" / "agent-active-99999"
        agent_dir.mkdir(parents=True, exist_ok=True)
        _write_file(agent_dir / "work.txt", "agent working file\n")

        result = run_merge(merge_env)
        assert result.exit_code == 0


# ===========================================================================
# Tests: Remote cleanup
# ===========================================================================
class TestRemoteCleanup:
    """Remote branch deletion."""


    def test_remote_delete_failure_warns_and_preserves_retry_lane(
        self, cleanup_context, monkeypatch, capsys,
    ) -> None:
        """A refused remote deletion warns and retains local retry state."""
        cleanup_context.args.standalone = False
        delete = mock.Mock(return_value=RemoteBranchDeleteResult(
            "preserved", "leased remote delete was refused",
        ))
        monkeypatch.setattr(cleanup, "delete_remote_branch_if_merged", delete)
        assert cleanup._post_merge_cleanup(cleanup_context, no_changes=False) == 0
        delete.assert_called_once()
        assert delete.call_args.kwargs["branch"] == "feature"
        output = capsys.readouterr()
        assert "WARNING: Preserving remote branch feature: leased remote delete was refused" in output.err
        assert "Preserving local worktree and branch" in output.err
        assert not any(call.args[0][0] in {"worktree", "branch"}
                       for call in engine._run_git.call_args_list)


# ===========================================================================
# Tests: Cleanup
# ===========================================================================
class TestCleanupTrap:
    """Cleanup trap removes trial branch on error."""

    def test_yok495_cleanup_trap_removes_trial_branch(
        self, merge_env: MergeEnv
    ) -> None:
        """Trap cleans up trial branch on error."""
        repo = merge_env.repo

        # Find real git
        real_git = subprocess.run(
            ["which", "git"], capture_output=True, text=True, check=True
        ).stdout.strip()

        # Create git mock that fails on 'checkout YOK-N' (without -b)
        git_mock_dir = merge_env.tmpdir / "git-mock"
        git_mock_dir.mkdir(parents=True, exist_ok=True)
        git_mock_script = textwrap.dedent(f"""\
            #!/usr/bin/env sh
            _has_b=0
            _has_checkout=0
            _has_branch_name=0
            for _a in "$@"; do
              case "$_a" in
                -b) _has_b=1 ;;
                checkout) _has_checkout=1 ;;
                {TEST_BRANCH}) _has_branch_name=1 ;;
              esac
            done
            if [ "$_has_checkout" -eq 1 ] && [ "$_has_branch_name" -eq 1 ] && [ "$_has_b" -eq 0 ]; then
              "{real_git}" checkout --detach HEAD 2>/dev/null || true
              echo "mock git: simulated checkout failure" >&2
              exit 1
            fi
            exec "{real_git}" "$@"
        """)
        git_mock_path = git_mock_dir / "git"
        git_mock_path.write_text(git_mock_script)
        git_mock_path.chmod(git_mock_path.stat().st_mode | 0o111)

        git_mock_test_path = f"{git_mock_dir}:{merge_env.test_path}"

        env_overrides = merge_env.env(extra={"PATH": git_mock_test_path})
        env_overrides.setdefault("PYTHONPATH", str(WORKTREE_ROOT))
        subprocess.run(
            [sys.executable, "-m", MERGE_MODULE, TEST_BRANCH, "main"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=env_overrides,
            check=False,
        )

        # Python engine may succeed where shell failed; verify no trial branch remains
        branch_list = subprocess.run(
            [real_git, "branch", "--list", f"trial/{TEST_BRANCH}"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        assert f"trial/{TEST_BRANCH}" not in branch_list.stdout
