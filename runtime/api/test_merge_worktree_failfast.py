"""Merge fail-fast + existing-PR reuse + freshness coverage via REST seam.

These tests cover the production regressions surfaced during the
harness-hook usher incident on 2026-04-10, and the REST migration in
YOK-1839 (bearer-token REST instead of ``gh`` CLI). Each test seeds:

- a ``yoke`` project with ``github_repo='anthropics/yoke'``
- a verified GitHub App installation and project repo binding
- ``items.project_id`` pointing at Yoke so the engine's auth precondition resolves
- ``YOKE_REST_FAKE_DIR`` pointing at per-test canned response files
  produced by :mod:`runtime.api.merge_worktree_test_rest_fakes`

The mock-``gh`` PATH script is still installed for the residual
operations the engine performs against the origin repo (the post-merge
``do_local_merge`` style cleanup), but every PR-related REST call is
satisfied by the fake-dir files.
"""

# The shared pytest fixture intentionally shares its name with test parameters.
# ruff: noqa: F811

from __future__ import annotations

import pytest

from runtime.api import merge_worktree_test_rest_fakes as rest_fakes
from runtime.api.test_merge_worktree_full import (
    MergeEnv,
    _git,
    _write_file,
    merge_env as merge_env,
    run_merge,
)


@pytest.fixture
def rest_env(merge_env: MergeEnv):
    """Wrap ``merge_env`` and clear the shared fake-dir for per-test overrides.

    The shared ``merge_env`` fixture already seeds the ``yoke`` project,
    GitHub App installation and repo binding, binds the synthetic item row to
    ``project='yoke'``, and pre-populates the
    fake-dir with happy-path REST responses. Failfast tests need
    scenario-specific responses, so this fixture clears the fake-dir to
    a clean slate before each test.
    """
    fake_dir = merge_env.rest_fake_dir
    for f in fake_dir.iterdir() if fake_dir.exists() else []:
        f.unlink()
    fake_dir.mkdir(parents=True, exist_ok=True)
    return merge_env, fake_dir


def _run(rest_env, *, extra_env=None):
    env, _fake_dir = rest_env
    return run_merge(env, extra_env=extra_env)


def _branch():
    from runtime.api.test_merge_worktree_full import TEST_BRANCH

    return TEST_BRANCH


class TestYOK1362MergeFailFast:
    """Merge engine fail-fast + existing-PR reuse + freshness race."""

    def test_yok1362_pr_create_hard_fail_no_merge(self, rest_env) -> None:
        """POST /pulls returns 422 (non-already-exists) → exit 1, no merge call."""
        env, fake_dir = rest_env
        rest_fakes.write_pr_create_hard_fail(fake_dir)
        result = _run(rest_env)
        assert result.exit_code == 1
        assert "Successfully merged" not in result.stdout
        # The merge-call fake file is intentionally absent — a 422 on create
        # short-circuits before the merge call is ever issued.
        assert not (fake_dir / rest_fakes.pulls_merge_filename("9999")).exists()
        # Operator-facing stderr identifies the pr-create phase.
        assert "pr-create" in result.stderr.lower()

    def test_yok1362_empty_pr_url_never_merges(self, rest_env) -> None:
        """201 with empty body → identifier-validation failure, no merge."""
        env, fake_dir = rest_env
        rest_fakes.write_pr_create_empty_url(fake_dir)
        result = _run(rest_env)
        assert result.exit_code == 1
        assert "Successfully merged" not in result.stdout

    def test_yok1362_existing_pr_reused(self, rest_env) -> None:
        """422 already-exists → discover via list → reuse → merge proceeds."""
        env, fake_dir = rest_env
        rest_fakes.write_pr_exists_reuse(
            fake_dir, branch=_branch(), origin_path=str(env.origin)
        )
        result = _run(rest_env)
        assert result.exit_code == 0, (
            f"reuse path must succeed; stdout=\n{result.stdout}\n"
            f"stderr=\n{result.stderr}"
        )
        assert "Reusing existing PR" in result.stdout
        assert "Successfully merged" in result.stdout

    def test_yok1362_existing_pr_unresolvable(self, rest_env) -> None:
        """422 already-exists + empty list → hard failure, no merge."""
        env, fake_dir = rest_env
        rest_fakes.write_pr_exists_unresolvable(fake_dir, branch=_branch())
        result = _run(rest_env)
        assert result.exit_code == 1
        assert "Successfully merged" not in result.stdout

    def test_yok1362_pr_merge_failure_no_false_success(self, rest_env) -> None:
        """REST /merge returns 409 → exit 1, no false success line."""
        env, fake_dir = rest_env
        rest_fakes.write_pr_merge_fail(fake_dir, branch=_branch())
        result = _run(rest_env)
        assert result.exit_code == 1
        assert "Successfully merged" not in result.stdout
        # Operator stderr identifies the pr-merge phase.
        assert "pr-merge" in result.stderr.lower()
        # Worktree preserved.
        wt_list = _git(env.repo, "worktree", "list", "--porcelain", check=False)
        assert str(env.worktree) in wt_list.stdout

    def test_yok1362_target_pushed_before_trial_merge(self, rest_env) -> None:
        """Local main ahead of origin is pushed before trial-merge runs."""
        env, fake_dir = rest_env
        rest_fakes.write_happy_path(
            fake_dir, branch=_branch(), origin_path=str(env.origin)
        )
        repo = env.repo
        _write_file(repo / "main-only.txt", "main-ahead commit\n")
        _git(repo, "add", "main-only.txt")
        _git(repo, "commit", "-m", "local main ahead of origin")

        origin_head_before = _git(
            repo, "rev-parse", "origin/main", check=False
        ).stdout.strip()
        local_head_before = _git(repo, "rev-parse", "main", check=False).stdout.strip()
        assert origin_head_before != local_head_before

        result = _run(rest_env)
        assert result.exit_code == 0, result.stderr
        assert "pushing before validation" in result.stdout
        origin_log = _git(
            repo, "log", "origin/main", "--oneline", "--all", check=False
        ).stdout
        assert "local main ahead of origin" in origin_log

    def test_yok1362_success_line_only_after_verification(self, rest_env) -> None:
        """Success line appears only after the in-origin verification block."""
        env, fake_dir = rest_env
        rest_fakes.write_happy_path(
            fake_dir, branch=_branch(), origin_path=str(env.origin)
        )
        result = _run(rest_env)
        assert result.exit_code == 0, result.stderr
        stdout = result.stdout
        success_idx = stdout.find("Successfully merged")
        verify_idx = stdout.find("Verified: branch commits present in origin/")
        assert success_idx >= 0, "success line missing on happy path"
        assert verify_idx >= 0, "verification line missing on happy path"
        assert verify_idx < success_idx

    def test_yok1362_no_checks_treated_as_no_ci(self, rest_env) -> None:
        """check-runs returning empty list → SKIPPED_NO_CHECKS path."""
        env, fake_dir = rest_env
        rest_fakes.write_happy_path(
            fake_dir, branch=_branch(), origin_path=str(env.origin)
        )
        result = _run(rest_env)
        assert result.exit_code == 0, result.stderr
        assert "(No CI checks configured" in result.stdout
        assert "Successfully merged" in result.stdout
