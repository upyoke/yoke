from __future__ import annotations

from runtime.api.test_merge_worktree_pr_checks_test_helpers import _stub_ctx


_PYTEST_PASS_OUTPUT = (
    "============================= test session starts ==============================\n"
    "collected 12 items\n\n"
    "tests/test_foo.py ............                                          [100%]\n\n"
    "============================== 12 passed in 1.42s =============================="
)
_PYTEST_FAILED_OUTPUT = (
    "============================= test session starts ==============================\n"
    "collected 12 items\n\n"
    "tests/test_foo.py ...F........                                          [100%]\n\n"
    "FAILED tests/test_foo.py::test_bar - AssertionError\n"
    "=========================== 1 failed, 11 passed ============================="
)

# Full 40-hex SHAs for the freshness-binding tests. The merge gate accepts a
# PASS verdict only when its stamped head-SHA matches the PR head SHA. Shared
# with ``test_merge_worktree_freshness`` which imports them from here.
_HEAD_SHA = "abc1234def56789012345678901234567890abcd"
_OTHER_SHA = "9999999000000000000000000000000000000000"


def _stamp(output: str, sha: str) -> str:
    """Append the canonical head-SHA trailer to a captured verdict blob."""
    from yoke_core.domain.item_test_results_classify import (
        format_verdict_head_sha_trailer,
    )

    return output + "\n\n" + format_verdict_head_sha_trailer(sha)


def _event_names(emitted):
    return [name for (name, _kw) in emitted]


def _arm_pr_merge_environment(
    monkeypatch, *, ci_outcome, test_results: str, head_sha: str = _HEAD_SHA
):
    """Stub every helper upstream of the CI branch so the test sees only the
    gate's decision-making. Shared with ``test_merge_worktree_freshness``."""
    import subprocess
    from yoke_core.engines import merge_worktree
    from yoke_core.engines import merge_worktree_pr
    from yoke_core.engines import merge_worktree_pr_rest

    emitted: list[tuple[str, dict]] = []

    def _capture_event(event_name, **kw):
        emitted.append((event_name, kw))

    monkeypatch.setattr(merge_worktree, "_emit_merge_event", _capture_event)
    monkeypatch.setattr(
        merge_worktree_pr, "_wait_for_ci", lambda *_a, **_kw: ci_outcome
    )
    # Freshness binding: the gate reads the PR head SHA to verify the local
    # verdict is bound to the merged commit.
    monkeypatch.setattr(
        merge_worktree_pr,
        "get_pr_head_sha",
        lambda *_a, **_kw: (head_sha, None),
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "_read_item_test_results",
        lambda _item: test_results,
    )
    monkeypatch.setattr(
        merge_worktree,
        "_run_git",
        lambda *_a, **_kw: subprocess.CompletedProcess(
            [], 0, stdout="aaa\n", stderr=""
        ),
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "create_pr",
        lambda *_a, **_kw: merge_worktree_pr_rest.PrCreateResult(
            pr_url="https://example/repo/pull/9999",
            pr_num="9999",
        ),
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "find_existing_pr",
        lambda *_a, **_kw: (None, None),
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "run_pr_merge_with_retry_guard",
        lambda *_a, **_kw: merge_worktree_pr_rest.PrMergeResult(success=True),
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "_post_merge_cleanup",
        lambda *_a, **_kw: 0,
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "_current_origin_target_sha",
        lambda *_a, **_kw: None,
    )
    return emitted


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
                None, "check-runs REST authorization failed: HTTP 403",
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
                merge_worktree_ci_rest.CheckRunsState(
                    states=("SUCCESS", "SUCCESS")
                ),
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

        assert _classify_test_results(
            "tests/test_foo.py::test_bar ERROR\n=== 1 errors in 0.5s ==="
        ) == "failed"

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
            kw
            for (name, kw) in emitted
            if name == "MergeBlockedNoVerificationEvidence"
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
