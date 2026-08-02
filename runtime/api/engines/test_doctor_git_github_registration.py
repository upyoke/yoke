"""Registration and selection coverage for GitHub-dependent doctor checks."""

from yoke_core.engines.doctor import DoctorArgs, HEALTH_CHECKS, _should_run_hc


class TestQuickMode:
    def test_quick_skips_github_hcs(self):
        args = DoctorArgs(quick=True)
        assert not _should_run_hc("orphaned-gh-issues", args)
        assert not _should_run_hc("stale-remote-branches", args)
        assert not _should_run_hc("wrong-repo-issues", args)
        assert not _should_run_hc("delegated-sync", args)

    def test_quick_allows_git_hcs(self):
        args = DoctorArgs(quick=True)
        assert _should_run_hc("main-checkout", args)
        assert _should_run_hc("worktree-health", args)


class TestOnlyDelegatedSync:
    def test_only_title_drift_triggers_delegated(self):
        assert _should_run_hc("delegated-sync", DoctorArgs(only="title-drift"))

    def test_only_unrelated_does_not_trigger_delegated(self):
        assert not _should_run_hc("delegated-sync", DoctorArgs(only="main-checkout"))


class TestHcRegistration:
    def test_git_hcs_registered(self):
        slugs = {hc.slug for hc in HEALTH_CHECKS}
        for expected in (
            "main-checkout",
            "worktree-health",
            "branch-divergence",
            "uncaptured-discoveries",
            "orphaned-stashes",
            "cross-project-commits",
            "epic-task-worktree-backfill",
            "path-confabulation",
            "orphaned-temp-files",
        ):
            assert expected in slugs

    def test_github_hcs_registered_and_dependent(self):
        slugs = {hc.slug for hc in HEALTH_CHECKS}
        expected = (
            "stale-remote-branches",
            "orphaned-gh-issues",
            "gh-orphan-detection",
            "wrong-repo-issues",
            "delegated-sync",
        )
        assert set(expected).issubset(slugs)
        assert all(hc.github_dependent for hc in HEALTH_CHECKS if hc.slug in expected)
