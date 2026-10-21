"""State assertions consume the journey that actually produced their state."""

from yoke_cli.config.onboard_plan_labels import friendly_line
from runtime.api.domain.test_qa_release_channel_target import _target
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)


def _cases():
    return installer_campaign_cases_for_target(
        _target("prod"), primary_machine="primary", joining_machine="joining"
    )


def test_state_checks_directly_follow_their_real_state_producers():
    cases = _cases()
    keys = [case["case_key"] for case in cases]
    for producer, consumer in (
        ("apply-handoff", "universe-born"),
    ):
        assert keys[keys.index(producer) + 1] == consumer
        assert cases[keys.index(consumer)]["starting_state"] == "inherit"
    assert [case["position"] for case in cases] == list(range(1, len(cases) + 1))


def test_token_permissions_are_proven_inside_cold_start_before_restore():
    cases = _cases()
    assert not any(case["case_key"] == "token-perms" for case in cases)
    cold = next(case for case in cases if case["case_key"] == "cold-start-hosted")
    for field in ("instructions", "expected_outcome"):
        assert "token-file-exists" in cold[field]
        assert "secrets-directory-mode-700" in cold[field]
        assert "token-file-modes-600" in cold[field]
        assert "without" in cold[field] and "contents" in cold[field]
    assert "Before walk-end" in cold["instructions"]


def test_review_captures_the_write_names_and_backs_out_without_apply():
    case = next(case for case in _cases() if case["case_key"] == "review-frame")
    assert case["method_id"] == "exploratory-mission"
    reuse_line = friendly_line("reuse-session-relay-token", "")
    assert reuse_line in case["expected_outcome"]
    assert "Show all changes" in case["instructions"]
    assert "Show summary" in case["expected_outcome"]
    assert "back out without Apply" in case["instructions"]
    assert "Category counts alone" in case["instructions"]
    assert case["required_completion"] == "back-before-apply"


def test_no_case_inherits_state_after_a_mission():
    cases = _cases()
    for previous, case in zip(cases, cases[1:]):
        if previous["method_id"] == "exploratory-mission":
            assert case["starting_state"] != "inherit"
