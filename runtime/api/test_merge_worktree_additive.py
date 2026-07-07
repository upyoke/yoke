"""
test_merge_worktree_additive.py — Additive conflict resolution tests.
Shared fixtures live in test_merge_worktree_full.py.
"""

from pathlib import Path

from runtime.api.test_merge_worktree_full import (
    TEST_BRANCH,
    MergeEnv,
    _git,
    _write_file,
    merge_env,  # re-export so pytest recognises this fixture
    run_merge,
)


class TestAdditiveConflictResolution:
    """Additive conflict auto-resolution."""

    def _create_shared_test_file(self, repo: Path) -> None:
        """Create a shared test file on main."""
        _write_file(
            repo / "shared-tests.sh",
            '#!/usr/bin/env sh\ntest_existing() {\n  echo "existing test"\n}\n',
        )
        _git(repo, "add", "shared-tests.sh")
        _git(repo, "commit", "-m", "add shared test file")
        _git(repo, "push", "origin", "main")

    def test_yok1205_trial_additive_auto_resolves(self, merge_env: MergeEnv) -> None:
        """Additive conflict auto-resolves."""
        repo = merge_env.repo
        wt = merge_env.worktree

        self._create_shared_test_file(repo)
        _git(wt, "pull", "origin", "main", "--rebase")

        # Feature adds tests
        with open(wt / "shared-tests.sh", "a") as f:
            f.write('\ntest_feature_a() {\n  echo "feature A test"\n}\n')
        _git(wt, "add", "shared-tests.sh")
        _git(wt, "commit", "-m", "add feature A tests")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        # Main adds different tests
        with open(repo / "shared-tests.sh", "a") as f:
            f.write('\ntest_main_b() {\n  echo "main B test"\n}\n')
        _git(repo, "add", "shared-tests.sh")
        _git(repo, "commit", "-m", "add main B tests")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "additive" in result.stdout.lower()

    def test_yok1205_trial_overlapping_exits_3(self, merge_env: MergeEnv) -> None:
        """Overlapping conflict exits 3 with structured output."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(
            repo / "shared-code.sh",
            '#!/usr/bin/env sh\nconfig_value="original"\necho "$config_value"\n',
        )
        _git(repo, "add", "shared-code.sh")
        _git(repo, "commit", "-m", "add shared code")
        _git(repo, "push", "origin", "main")

        _git(wt, "pull", "origin", "main", "--rebase")

        # Feature modifies existing line
        content = (wt / "shared-code.sh").read_text()
        content = content.replace('config_value="original"', 'config_value="feature_version"')
        _write_file(wt / "shared-code.sh", content)
        _git(wt, "add", "shared-code.sh")
        _git(wt, "commit", "-m", "change config to feature version")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        # Main also modifies same line
        content = (repo / "shared-code.sh").read_text()
        content = content.replace('config_value="original"', 'config_value="main_version"')
        _write_file(repo / "shared-code.sh", content)
        _git(repo, "add", "shared-code.sh")
        _git(repo, "commit", "-m", "change config to main version")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 3
        assert "CONFLICT|shared-code.sh|overlapping" in result.stderr
        assert "agent resolution" in result.stderr
        assert "real branch is untouched" in result.stderr

    def test_yok1205_real_merge_additive(self, merge_env: MergeEnv) -> None:
        """Real merge preserves both sides in additive conflict."""
        repo = merge_env.repo
        wt = merge_env.worktree

        self._create_shared_test_file(repo)
        _git(wt, "pull", "origin", "main", "--rebase")

        # Feature adds tests
        with open(wt / "shared-tests.sh", "a") as f:
            f.write('\ntest_feature_x() {\n  echo "feature X test"\n}\n')
        _git(wt, "add", "shared-tests.sh")
        _git(wt, "commit", "-m", "add feature X tests")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        # Main adds different tests
        with open(repo / "shared-tests.sh", "a") as f:
            f.write('\ntest_main_y() {\n  echo "main Y test"\n}\n')
        _git(repo, "add", "shared-tests.sh")
        _git(repo, "commit", "-m", "add main Y tests")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0

        # Check merged content on main
        _git(repo, "pull", "origin", "main", "--rebase", check=False)
        merged = _git(repo, "show", "HEAD:shared-tests.sh", check=False).stdout
        assert "test_feature_x" in merged
        assert "test_main_y" in merged
        assert "test_existing" in merged
        assert "additive conflict" in result.stdout

    def test_yok1205_existing_resolution_preserved(self, merge_env: MergeEnv) -> None:
        """Mixed yoke-gen + additive uses both resolution paths."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(
            repo / "code-tests.sh",
            '#!/usr/bin/env sh\ntest_base() {\n  echo "base"\n}\n',
        )
        _git(repo, "add", "code-tests.sh")
        _git(repo, "commit", "-m", "add base code")
        _git(repo, "push", "origin", "main")

        _git(wt, "pull", "origin", "main", "--rebase")

        # Feature: gen file + code additions
        _write_file(wt / ".yoke" / "BOARD.md", "# Feature board\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        with open(wt / "code-tests.sh", "a") as f:
            f.write('\ntest_feature_z() {\n  echo "feature Z"\n}\n')
        _git(wt, "add", "code-tests.sh")
        _git(wt, "commit", "-m", "feature changes")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        # Main: different changes in both
        _write_file(repo / ".yoke" / "BOARD.md", "# Main board\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md")
        with open(repo / "code-tests.sh", "a") as f:
            f.write('\ntest_main_w() {\n  echo "main W"\n}\n')
        _git(repo, "add", "code-tests.sh")
        _git(repo, "commit", "-m", "main changes")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "generated view conflict" in result.stdout
        assert "additive conflict" in result.stdout

    def test_yok1205_classifier_rejects_deletions(self, merge_env: MergeEnv) -> None:
        """Deletions mean not additive, exits 3."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(
            repo / "config.sh",
            '#!/usr/bin/env sh\nOLD_SETTING="remove_me"\nKEEP_SETTING="keep"\n',
        )
        _git(repo, "add", "config.sh")
        _git(repo, "commit", "-m", "add config")
        _git(repo, "push", "origin", "main")

        _git(wt, "pull", "origin", "main", "--rebase")

        # Feature: delete OLD_SETTING, add new
        _write_file(
            wt / "config.sh",
            '#!/usr/bin/env sh\nKEEP_SETTING="keep"\nNEW_FEATURE="added"\n',
        )
        _git(wt, "add", "config.sh")
        _git(wt, "commit", "-m", "replace old setting with feature")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        # Main: modify OLD_SETTING
        content = (repo / "config.sh").read_text()
        content = content.replace('OLD_SETTING="remove_me"', 'OLD_SETTING="updated"')
        _write_file(repo / "config.sh", content)
        _git(repo, "add", "config.sh")
        _git(repo, "commit", "-m", "update old setting on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 3
        assert "overlapping" in result.stderr
