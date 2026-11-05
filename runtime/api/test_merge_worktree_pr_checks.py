from __future__ import annotations

from runtime.api.merge_worktree_pr_checks_test_support import (
    _HEAD_SHA as _HEAD_SHA,
    _OTHER_SHA as _OTHER_SHA,
    _PYTEST_FAILED_OUTPUT as _PYTEST_FAILED_OUTPUT,
    _PYTEST_PASS_OUTPUT as _PYTEST_PASS_OUTPUT,
    _arm_pr_merge_environment as _arm_pr_merge_environment,
    _event_names as _event_names,
    _stamp as _stamp,
)


from runtime.api.merge_worktree_pr_checks_test_helpers_test_support import _stub_ctx


# Full 40-hex SHAs for the freshness-binding tests. The merge gate accepts a
# PASS verdict only when its stamped head-SHA matches the PR head SHA. Shared
# with ``test_merge_worktree_freshness`` which imports them from here.


class TestRestCheckRunsBranches:
    """The REST CI poller routes empty / no-checks responses to SKIPPED."""

    def test_no_check_runs_skips_cleanly(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree
        from yoke_core.engines import merge_worktree_ci_rest

        emitted: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            merge_worktree,
            "_emit_merge_event",
            lambda name, **kw: emitted.append((name, kw)),
        )
        from yoke_core.engines import merge_worktree_ci

        monkeypatch.setattr(
            merge_worktree_ci,
            "get_check_runs",
            lambda *_a, **_kw: (
                merge_worktree_ci_rest.CheckRunsState(states=()),
                None,
            ),
        )

        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "skipped"
        assert outcome.reason == "no_checks_configured"
        assert not [name for (name, _) in emitted if name == "MergePullRequestCiFailed"]

    def test_check_runs_authorization_failure_fails_closed(self, monkeypatch) -> None:
        """Token lacking required Checks read permission blocks the merge."""
        from yoke_core.engines import merge_worktree

        monkeypatch.setattr(
            merge_worktree,
            "_emit_merge_event",
            lambda name, **kw: None,
        )
        from yoke_core.engines import merge_worktree_ci

        monkeypatch.setattr(
            merge_worktree_ci,
            "get_check_runs",
            lambda *_a, **_kw: (
                None,
                "check-runs REST authorization failed: HTTP 403",
            ),
        )

        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "failed"

    def test_all_success_states_pass(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree
        from yoke_core.engines import merge_worktree_ci_rest

        monkeypatch.setattr(
            merge_worktree,
            "_emit_merge_event",
            lambda name, **kw: None,
        )
        from yoke_core.engines import merge_worktree_ci

        monkeypatch.setattr(
            merge_worktree_ci,
            "get_check_runs",
            lambda *_a, **_kw: (
                merge_worktree_ci_rest.CheckRunsState(states=("SUCCESS", "SUCCESS")),
                None,
            ),
        )

        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "passed"


class TestClassifyTestResults:
    """Direct coverage for ``_classify_test_results`` PASS-verdict parser."""

    def test_empty_string_classifies_empty(self) -> None:
        from yoke_core.engines.merge_worktree_ci import _classify_test_results

        assert _classify_test_results("") == "empty"
        assert _classify_test_results("   \n  ") == "empty"

    def test_pass_verdict_classifies_passed(self) -> None:
        from yoke_core.engines.merge_worktree_ci import _classify_test_results

        assert _classify_test_results(_PYTEST_PASS_OUTPUT) == "passed"

    def test_failed_signature_classifies_failed(self) -> None:
        from yoke_core.engines.merge_worktree_ci import _classify_test_results

        assert _classify_test_results(_PYTEST_FAILED_OUTPUT) == "failed"

    def test_error_signature_classifies_failed(self) -> None:
        from yoke_core.engines.merge_worktree_ci import _classify_test_results

        assert (
            _classify_test_results(
                "tests/test_foo.py::test_bar ERROR\n=== 1 errors in 0.5s ==="
            )
            == "failed"
        )

    def test_unrecognized_output_classifies_empty(self) -> None:
        """Ambiguous text without a PASS verdict must fall through to empty."""
        from yoke_core.engines.merge_worktree_ci import _classify_test_results

        assert _classify_test_results("running tests...") == "empty"


class TestSkippedCiGate:
    """Merge gate behavior on the skipped-CI branch — the empty / failed /
    real-CI-passed paths. Freshness-binding scenarios (fresh / stale / unbound)
    live in ``test_merge_worktree_freshness``."""

    def test_skipped_ci_with_fresh_pass_proceeds(self, monkeypatch) -> None:
        from yoke_core.engines.merge_worktree_ci import SKIPPED_NO_CHECKS
        from yoke_core.engines.merge_worktree_pr import do_pr_merge

        emitted = _arm_pr_merge_environment(
            monkeypatch,
            ci_outcome=SKIPPED_NO_CHECKS,
            test_results=_stamp(_PYTEST_PASS_OUTPUT, _HEAD_SHA),
        )
        rc = do_pr_merge(_stub_ctx())
        assert rc == 0, "skipped CI + fresh head-bound PASS must allow the merge"
        names = _event_names(emitted)
        assert "MergePullRequestCiSkipped" in names
        assert "LocalVerificationAcceptedAsCiSubstitute" in names
        assert "MergePullRequestCiPassed" not in names
        assert "MergeBlockedNoVerificationEvidence" not in names

    def test_skipped_ci_with_empty_evidence_blocks(self, monkeypatch) -> None:
        from yoke_core.engines.merge_worktree_ci import SKIPPED_NO_CHECKS
        from yoke_core.engines.merge_worktree_pr import do_pr_merge

        emitted = _arm_pr_merge_environment(
            monkeypatch, ci_outcome=SKIPPED_NO_CHECKS, test_results=""
        )
        rc = do_pr_merge(_stub_ctx())
        assert rc == 1, "skipped CI + empty test_results must block the merge"
        names = _event_names(emitted)
        assert "MergePullRequestCiSkipped" in names
        assert "MergeBlockedNoVerificationEvidence" in names
        assert "MergePullRequestCiPassed" not in names
        assert "LocalVerificationAcceptedAsCiSubstitute" not in names

    def test_skipped_ci_with_failed_evidence_blocks(self, monkeypatch) -> None:
        from yoke_core.engines.merge_worktree_ci import SKIPPED_NO_CHECKS
        from yoke_core.engines.merge_worktree_pr import do_pr_merge

        emitted = _arm_pr_merge_environment(
            monkeypatch,
            ci_outcome=SKIPPED_NO_CHECKS,
            test_results=_PYTEST_FAILED_OUTPUT,
        )
        rc = do_pr_merge(_stub_ctx())
        assert rc == 1, "skipped CI + FAILED signature must block the merge"
        names = _event_names(emitted)
        assert "MergePullRequestCiSkipped" in names
        assert "MergeBlockedNoVerificationEvidence" in names
        assert "MergePullRequestCiPassed" not in names
        assert "LocalVerificationAcceptedAsCiSubstitute" not in names
        block_event = next(
            kw for (name, kw) in emitted if name == "MergeBlockedNoVerificationEvidence"
        )
        assert block_event["context"]["evidence_state"] == "failed"

    def test_actual_ci_passed_still_emits_passed(self, monkeypatch) -> None:
        from yoke_core.engines.merge_worktree_ci import PASSED
        from yoke_core.engines.merge_worktree_pr import do_pr_merge

        emitted = _arm_pr_merge_environment(
            monkeypatch, ci_outcome=PASSED, test_results=""
        )
        rc = do_pr_merge(_stub_ctx())
        assert rc == 0, "real CI passed must allow the merge unchanged"
        names = _event_names(emitted)
        assert "MergePullRequestCiPassed" in names
        assert "MergePullRequestCiSkipped" not in names
        assert "LocalVerificationAcceptedAsCiSubstitute" not in names
        assert "MergeBlockedNoVerificationEvidence" not in names

    def test_replay_pr_4312_shape_blocked_without_evidence(self, monkeypatch) -> None:
        from yoke_core.engines.merge_worktree_ci import SKIPPED_NO_CHECKS
        from yoke_core.engines.merge_worktree_pr import do_pr_merge

        emitted = _arm_pr_merge_environment(
            monkeypatch, ci_outcome=SKIPPED_NO_CHECKS, test_results=""
        )
        rc = do_pr_merge(_stub_ctx())
        assert rc == 1
        names = _event_names(emitted)
        assert "MergeBlockedNoVerificationEvidence" in names
        assert "MergePullRequestCiPassed" not in names
