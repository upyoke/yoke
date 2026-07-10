"""Freshness-binding coverage for the merge CI-substitute gate.

Split out of ``test_merge_worktree_pr_checks`` to honor the 350-line
authored-file cap. Covers:

- ``item_test_results_classify`` head-SHA trailer helpers (pure functions).
- ``evaluate_ci_substitute`` decision matrix (pure function).
- ``do_pr_merge`` skipped-CI gate freshness routing (fresh / stale / unbound
  / unresolved-head) — AC-1 / AC-5 / AC-10.
- ``_wait_for_ci`` declared-workflow registration wait — AC-8.

The merge-harness stubs (``_arm_pr_merge_environment`` etc.) live in
``test_merge_worktree_pr_checks`` and are imported here so both suites share
one source of truth.
"""

from __future__ import annotations

from runtime.api.test_merge_worktree_pr_checks_test_helpers import _stub_ctx
from runtime.api.test_merge_worktree_pr_checks import (
    _HEAD_SHA,
    _OTHER_SHA,
    _PYTEST_FAILED_OUTPUT,
    _PYTEST_PASS_OUTPUT,
    _arm_pr_merge_environment,
    _event_names,
    _stamp,
)


class TestVerdictHeadShaBinding:
    """Pure-function coverage for the head-SHA trailer helpers."""

    def test_format_and_extract_roundtrip(self) -> None:
        from yoke_core.domain.item_test_results_classify import (
            extract_verdict_head_sha,
            format_verdict_head_sha_trailer,
        )

        trailer = format_verdict_head_sha_trailer(_HEAD_SHA)
        assert _HEAD_SHA in trailer
        body = _PYTEST_PASS_OUTPUT + "\n\n" + trailer
        assert extract_verdict_head_sha(body) == _HEAD_SHA

    def test_format_rejects_non_sha(self) -> None:
        from yoke_core.domain.item_test_results_classify import (
            format_verdict_head_sha_trailer,
        )

        assert format_verdict_head_sha_trailer("") == ""
        assert format_verdict_head_sha_trailer("not-a-sha") == ""

    def test_extract_missing_returns_none(self) -> None:
        from yoke_core.domain.item_test_results_classify import (
            extract_verdict_head_sha,
        )

        assert extract_verdict_head_sha(_PYTEST_PASS_OUTPUT) is None
        assert extract_verdict_head_sha("") is None

    def test_extract_uses_last_occurrence(self) -> None:
        from yoke_core.domain.item_test_results_classify import (
            extract_verdict_head_sha,
            format_verdict_head_sha_trailer,
        )

        body = (
            format_verdict_head_sha_trailer(_OTHER_SHA)
            + "\n"
            + format_verdict_head_sha_trailer(_HEAD_SHA)
        )
        assert extract_verdict_head_sha(body) == _HEAD_SHA

    def test_verdict_is_fresh_exact_and_prefix(self) -> None:
        from yoke_core.domain.item_test_results_classify import verdict_is_fresh

        fresh = _stamp(_PYTEST_PASS_OUTPUT, _HEAD_SHA)
        assert verdict_is_fresh(fresh, _HEAD_SHA) is True
        # An abbreviated head sha still matches the full stamp.
        assert verdict_is_fresh(fresh, _HEAD_SHA[:12]) is True

    def test_verdict_not_fresh_on_mismatch_or_unbound(self) -> None:
        from yoke_core.domain.item_test_results_classify import verdict_is_fresh

        assert (
            verdict_is_fresh(_stamp(_PYTEST_PASS_OUTPUT, _OTHER_SHA), _HEAD_SHA)
            is False
        )
        assert verdict_is_fresh(_PYTEST_PASS_OUTPUT, _HEAD_SHA) is False
        assert verdict_is_fresh(_stamp(_PYTEST_PASS_OUTPUT, _HEAD_SHA), "") is False

    def test_trailer_does_not_perturb_classify(self) -> None:
        """AC-7: the HTML-comment trailer must not change classification."""
        from yoke_core.domain.item_test_results_classify import (
            classify_test_results,
        )

        assert (
            classify_test_results(_stamp(_PYTEST_PASS_OUTPUT, _HEAD_SHA))
            == "passed"
        )
        assert (
            classify_test_results(_stamp(_PYTEST_FAILED_OUTPUT, _HEAD_SHA))
            == "failed"
        )


class TestEvaluateCiSubstitute:
    """Pure-function coverage for the substitute-accept decision matrix."""

    def _ev(self, *args):
        from yoke_core.domain.item_test_results_classify import (
            evaluate_ci_substitute,
        )

        return evaluate_ci_substitute(*args)

    def test_fresh_pass_accepts(self) -> None:
        accept, state, _ = self._ev(
            "passed", _stamp(_PYTEST_PASS_OUTPUT, _HEAD_SHA), _HEAD_SHA, None
        )
        assert accept is True
        assert state == "fresh"

    def test_stale_pass_refused(self) -> None:
        accept, state, _ = self._ev(
            "passed", _stamp(_PYTEST_PASS_OUTPUT, _OTHER_SHA), _HEAD_SHA, None
        )
        assert accept is False
        assert state == "stale_or_unbound"

    def test_unbound_pass_refused(self) -> None:
        accept, state, _ = self._ev(
            "passed", _PYTEST_PASS_OUTPUT, _HEAD_SHA, None
        )
        assert accept is False
        assert state == "stale_or_unbound"

    def test_unresolved_head_refused(self) -> None:
        accept, state, _ = self._ev(
            "passed", _stamp(_PYTEST_PASS_OUTPUT, _HEAD_SHA), "", "rest error"
        )
        assert accept is False
        assert state == "head_sha_unresolved"

    def test_empty_refused(self) -> None:
        accept, state, phrase = self._ev("empty", "", "", None)
        assert accept is False
        assert state == "empty"
        assert phrase == "empty"

    def test_failed_refused(self) -> None:
        accept, state, phrase = self._ev(
            "failed", _PYTEST_FAILED_OUTPUT, "", None
        )
        assert accept is False
        assert state == "failed"
        assert phrase == "a failure verdict"


class TestSkippedCiGateFreshness:
    """``do_pr_merge`` skipped-CI gate routed through the freshness binding."""

    def test_fresh_sha_warns(self, monkeypatch) -> None:
        """AC-1/AC-5: a head-bound PASS proceeds; the accept event is WARN
        severity and records the verdict head sha."""
        from yoke_core.engines.merge_worktree_ci import SKIPPED_NO_CHECKS
        from yoke_core.engines.merge_worktree_pr import do_pr_merge

        emitted = _arm_pr_merge_environment(
            monkeypatch,
            ci_outcome=SKIPPED_NO_CHECKS,
            test_results=_stamp(_PYTEST_PASS_OUTPUT, _HEAD_SHA),
            head_sha=_HEAD_SHA,
        )
        rc = do_pr_merge(_stub_ctx())
        assert rc == 0
        accept = next(
            kw
            for (name, kw) in emitted
            if name == "LocalVerificationAcceptedAsCiSubstitute"
        )
        assert accept.get("severity") == "WARN"
        assert accept["context"]["verdict_head_sha"] == _HEAD_SHA

    def test_stale_sha_blocks(self, monkeypatch) -> None:
        """AC-4: a real-but-stale PASS (stamped at a SHA other than the PR
        head — the YOK-1883 shape) is refused as a CI substitute."""
        from yoke_core.engines.merge_worktree_ci import SKIPPED_NO_CHECKS
        from yoke_core.engines.merge_worktree_pr import do_pr_merge

        emitted = _arm_pr_merge_environment(
            monkeypatch,
            ci_outcome=SKIPPED_NO_CHECKS,
            test_results=_stamp(_PYTEST_PASS_OUTPUT, _OTHER_SHA),
            head_sha=_HEAD_SHA,
        )
        rc = do_pr_merge(_stub_ctx())
        assert rc == 1, "a PASS not bound to the PR head SHA must block"
        names = _event_names(emitted)
        assert "MergeBlockedNoVerificationEvidence" in names
        assert "LocalVerificationAcceptedAsCiSubstitute" not in names
        block = next(
            kw
            for (name, kw) in emitted
            if name == "MergeBlockedNoVerificationEvidence"
        )
        assert block["context"]["evidence_state"] == "stale_or_unbound"

    def test_unbound_pass_blocks(self, monkeypatch) -> None:
        """AC-10: a legacy PASS with no head-SHA stamp is unbound and refused."""
        from yoke_core.engines.merge_worktree_ci import SKIPPED_NO_CHECKS
        from yoke_core.engines.merge_worktree_pr import do_pr_merge

        emitted = _arm_pr_merge_environment(
            monkeypatch,
            ci_outcome=SKIPPED_NO_CHECKS,
            test_results=_PYTEST_PASS_OUTPUT,  # no head-sha trailer
            head_sha=_HEAD_SHA,
        )
        rc = do_pr_merge(_stub_ctx())
        assert rc == 1, "an unstamped PASS must block (no fresh binding)"
        names = _event_names(emitted)
        assert "MergeBlockedNoVerificationEvidence" in names
        assert "LocalVerificationAcceptedAsCiSubstitute" not in names

    def test_unresolved_head_sha_blocks(self, monkeypatch) -> None:
        """Fail-closed: a PASS blocks when the PR head SHA cannot be read."""
        from yoke_core.engines.merge_worktree_ci import SKIPPED_NO_CHECKS
        from yoke_core.engines import merge_worktree_pr
        from yoke_core.engines.merge_worktree_pr import do_pr_merge

        emitted = _arm_pr_merge_environment(
            monkeypatch,
            ci_outcome=SKIPPED_NO_CHECKS,
            test_results=_stamp(_PYTEST_PASS_OUTPUT, _HEAD_SHA),
        )
        monkeypatch.setattr(
            merge_worktree_pr,
            "get_pr_head_sha",
            lambda *_a, **_kw: ("", "pulls/9999 REST read failed"),
        )
        rc = do_pr_merge(_stub_ctx())
        assert rc == 1
        block = next(
            kw
            for (name, kw) in emitted
            if name == "MergeBlockedNoVerificationEvidence"
        )
        assert block["context"]["evidence_state"] == "head_sha_unresolved"


class TestCheckRegistrationWait:
    """AC-8: empty check-runs + a declared workflow waits for registration
    before concluding no-CI; no declaration skips immediately."""

    def _arm(self, monkeypatch, *, declares, states_sequence, reg_timeout=120):
        from yoke_core.engines import merge_worktree
        from yoke_core.engines import merge_worktree_ci
        from yoke_core.engines import merge_worktree_ci_rest
        from yoke_core.domain import runtime_settings

        monkeypatch.setattr(
            merge_worktree, "_emit_merge_event", lambda *a, **k: None
        )
        monkeypatch.setattr(
            merge_worktree_ci,
            "_project_declares_ci_workflow",
            lambda _ctx: declares,
        )
        monkeypatch.setattr(merge_worktree_ci.time, "sleep", lambda *_a, **_k: None)

        seq = iter(states_sequence)

        def _fake_get_check_runs(*_a, **_k):
            try:
                st = next(seq)
            except StopIteration:
                st = states_sequence[-1]
            return (
                merge_worktree_ci_rest.CheckRunsState(states=st),
                None,
            )

        monkeypatch.setattr(
            merge_worktree_ci, "get_check_runs", _fake_get_check_runs
        )

        real_get_seconds = runtime_settings.get_seconds

        def _fake_get_seconds(key, default):
            if key == "ci_registration_timeout":
                return reg_timeout
            if key == "ci_poll_interval":
                return 1
            if key == "ci_timeout":
                return 5
            return real_get_seconds(key, default)

        monkeypatch.setattr(runtime_settings, "get_seconds", _fake_get_seconds)

    def test_checks_register_after_wait_then_classify(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree

        self._arm(
            monkeypatch, declares=True, states_sequence=[(), (), ("SUCCESS",)]
        )
        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "passed"

    def test_checks_register_red_blocks(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree

        self._arm(
            monkeypatch, declares=True, states_sequence=[(), ("FAILURE",)]
        )
        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "failed"

    def test_checks_never_register_returns_unregistered(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree

        self._arm(
            monkeypatch, declares=True, states_sequence=[()], reg_timeout=3
        )
        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "skipped"
        assert outcome.reason == "checks_declared_unregistered"

    def test_no_declaration_skips_immediately(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree

        self._arm(monkeypatch, declares=False, states_sequence=[()])
        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "skipped"
        assert outcome.reason == "no_checks_configured"
